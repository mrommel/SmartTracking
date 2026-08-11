from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import render

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import (
	AttachmentForm, CommentForm, ComponentDeleteForm, ComponentForm,
	LabelDeleteForm, LabelForm, ProjectForm, SprintDeleteForm,
	TicketForm, TicketTransitionForm,
)
from .models import Attachment, Comment, Component, Label, Project, Sprint, Ticket, TicketRelation


@login_required
def dashboard(request):
	"""Landing page: high-level counts and the most recent activity."""
	tickets = Ticket.objects.all()
	total_tickets = tickets.count()

	# Counts keyed by state/priority value, so the template can look them up.
	state_counts = {
		row["state"]: row["count"]
		for row in tickets.values("state").annotate(count=Count("id"))
	}
	priority_counts = {
		row["priority"]: row["count"]
		for row in tickets.values("priority").annotate(count=Count("id"))
	}

	open_states = [Ticket.State.OPEN, Ticket.State.IN_PROGRESS]
	open_tickets = sum(state_counts.get(s, 0) for s in open_states)

	# Ordered (state, label, count) rows for the status breakdown widget.
	state_breakdown = [
		(state.value, state.label, state_counts.get(state.value, 0))
		for state in Ticket.State
	]

	recent_tickets = (
		tickets.select_related("project", "assignee").order_by("-created_at")[:8]
	)

	my_tickets = tickets.filter(assignee=request.user).count()
	unassigned = tickets.filter(assignee__isnull=True).count()

	return render(request, "tracking/dashboard.html", {
		"title": "Dashboard",
		"total_tickets": total_tickets,
		"open_tickets": open_tickets,
		"project_count": Project.objects.count(),
		"critical_count": priority_counts.get(Ticket.Priority.CRITICAL.value, 0),
		"state_breakdown": state_breakdown,
		"recent_tickets": recent_tickets,
		"my_tickets": my_tickets,
		"unassigned": unassigned,
	})


@login_required
def project_list(request):
	"""Show all projects with their ticket counts."""
	projects = Project.objects.annotate(ticket_count=Count("tickets")).order_by("key")
	return render(request, "tracking/project_list.html", {
		"title": "Projects",
		"projects": projects,
	})


@login_required
def project_detail(request, pk):
	"""Show a project with its tickets, components, and labels."""
	project = get_object_or_404(
		Project.objects.annotate(ticket_count=Count("tickets")), pk=pk
	)
	tickets = Ticket.objects.select_related("project", "assignee").filter(project=project)
	components = project.components.all()
	labels = project.labels.all()
	return render(request, "tracking/project_detail.html", {
		"title": project.key,
		"project": project,
		"tickets": tickets,
		"components": components,
		"labels": labels,
	})


@login_required
def project_create(request):
	"""Create a new project."""
	if request.method == "POST":
		form = ProjectForm(request.POST)
		if form.is_valid():
			project = form.save()
			messages.success(request, f"Project “{project.key}” created.")
			return redirect("project_list")
	else:
		form = ProjectForm()

	return render(request, "tracking/project_form.html", {
		"title": "New project",
		"form": form,
	})


@login_required
def ticket_list(request):
	"""List tickets, optionally filtered by project, state, component, and label."""
	tickets = Ticket.objects.select_related("project", "assignee")

	query = request.GET.get("q")
	if query:
		tickets = tickets.filter(
			Q(title__icontains=query) | Q(description__icontains=query)
		)

	project_key = request.GET.get("project")
	if project_key:
		tickets = tickets.filter(project__key=project_key)

	state = request.GET.get("state")
	if state:
		tickets = tickets.filter(state=state)

	component = request.GET.get("component")
	if component:
		tickets = tickets.filter(components__name=component)

	label = request.GET.get("label")
	if label:
		tickets = tickets.filter(labels__name=label)

	assignee = request.GET.get("assignee")
	if assignee == "me":
		tickets = tickets.filter(assignee=request.user)
	elif assignee == "unassigned":
		tickets = tickets.filter(assignee__isnull=True)
	elif assignee:
		tickets = tickets.filter(assignee__pk=assignee)

	return render(request, "tracking/ticket_list.html", {
		"title": "Tickets",
		"tickets": tickets,
		"projects": Project.objects.all(),
		"states": Ticket.State.choices,
		"current_project": project_key or "",
		"current_state": state or "",
		"current_component": component or "",
		"current_label": label or "",
		"current_assignee": assignee or "",
		"current_query": query or "",
		"components": Component.objects.all().order_by("name"),
		"labels": Label.objects.all().order_by("name"),
		"users": get_user_model().objects.filter(
			id__in=Ticket.objects.values_list("assignee", flat=True).distinct()
		).order_by("username"),
	})


@login_required
def ticket_detail(request, pk):
	"""Show a single ticket with its allowed state transitions, comments, and attachments."""
	ticket = get_object_or_404(
		Ticket.objects.select_related("project", "assignee", "reporter", "parent_epic"), pk=pk
	)
	comments = ticket.comments.select_related("author").all()
	attachments = ticket.attachments.all()
	child_tickets = Ticket.objects.filter(parent_epic=ticket).select_related("project", "assignee").all()
	relations = list(ticket.relations.prefetch_related("subject", "target").all())
	for rel in relations:
		if rel.subject_id == ticket.pk:
			rel.label = str(rel.get_relation_type_display())
		else:
			rel.label = ticket._get_reverse_label(rel.relation_type)
	return render(request, "tracking/ticket_detail.html", {
		"title": ticket.title,
		"ticket": ticket,
		"transition_form": TicketTransitionForm(ticket=ticket),
		"comment_form": CommentForm(),
		"comments": comments,
		"attachments": attachments,
		"relations": relations,
		"available_tickets": ticket.available_rels_for("current_project"),
		"relation_types": Ticket.RelationType.choices,
		"child_tickets": child_tickets,
	})


@login_required
def ticket_edit(request, pk):
	"""Edit an existing ticket."""
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == "POST":
		form = TicketForm(request.POST)
		if form.is_valid():
			for field in ["title", "description", "type", "estimation", "priority", "assignee", "parent_epic"]:
				setattr(ticket, field, form.cleaned_data[field])
			ticket.save(update_fields=["title", "description", "type", "estimation", "priority", "assignee", "parent_epic", "updated_at"])
			ticket.components.set(form.cleaned_data.get("components", []))
			ticket.labels.set(form.cleaned_data.get("labels", []))
			messages.success(request, "Ticket updated.")
			return redirect("ticket_detail", pk=ticket.pk)
	else:
		form = TicketForm(instance=ticket)
		project_key = ticket.project.key
		form.fields["parent_epic"].queryset = Ticket.objects.filter(project=ticket.project, type=Ticket.Type.EPIC).exclude(pk=ticket.pk)
		form.fields["components"].queryset = Component.objects.filter(project=ticket.project)
		form.fields["labels"].queryset = Label.objects.filter(project=ticket.project)

	return render(request, "tracking/ticket_form.html", {
		"title": f"Edit — {ticket.title}",
		"form": form,
		"ticket": ticket,
	})


@login_required
def ticket_create(request):
	"""Create a new ticket."""
	if request.method == "POST":
		form = TicketForm(request.POST)
		if form.is_valid():
			ticket = form.save(commit=False)
			if request.user.is_authenticated:
				ticket.reporter = request.user
			ticket.save()
			messages.success(request, "Ticket created.")
			return redirect("ticket_detail", pk=ticket.pk)
	else:
		form = TicketForm()
		# Pre-populate components/labels for the selected project
		project_key = request.GET.get("project")
		if project_key:
			form.fields["components"].queryset = Component.objects.filter(
				project__key=project_key.upper()
			)
			form.fields["labels"].queryset = Label.objects.filter(
				project__key=project_key.upper()
			)

	return render(request, "tracking/ticket_form.html", {
		"title": "New ticket",
		"form": form,
	})


@login_required
def ticket_transition(request, pk):
	"""Apply a state transition to a ticket if it is allowed."""
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == "POST":
		form = TicketTransitionForm(request.POST, ticket=ticket)
		if form.is_valid():
			ticket.state = form.cleaned_data["state"]
			ticket.save(update_fields=["state", "updated_at"])
			messages.success(request, f"Ticket moved to “{ticket.get_state_display()}”.")
		else:
			messages.error(request, "Invalid state transition.")
	return redirect(reverse("ticket_detail", args=[ticket.pk]))


@login_required
def ticket_comment_create(request, pk):
	"""Add a comment to a ticket."""
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == "POST":
		form = CommentForm(request.POST)
		if form.is_valid():
			comment = form.save(commit=False)
			comment.ticket = ticket
			comment.author = request.user
			comment.save()
			messages.success(request, "Comment added.")
			return redirect("ticket_detail", pk=ticket.pk)
	return redirect("ticket_detail", pk=ticket.pk)


@login_required
def ticket_relation_add(request, pk):
	"""Add a relation from the current ticket to another ticket."""
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == "POST":
		target_id = request.POST.get("target_ticket")
		relation_type = request.POST.get("relation_type")
		try:
			target = Ticket.objects.get(pk=target_id)
		except (ValueError, Ticket.DoesNotExist):
			messages.error(request, "Invalid target ticket.")
			return redirect("ticket_detail", pk=ticket.pk)
		if target.project != ticket.project:
			messages.error(request, "Target ticket must be in the same project.")
			return redirect("ticket_detail", pk=ticket.pk)
		if not relation_type:
			messages.error(request, "Please select a relation type.")
			return redirect("ticket_detail", pk=ticket.pk)
		# Check if the relation already exists
		if TicketRelation.objects.filter(
			subject=ticket, target=target, relation_type=relation_type
		).exists():
			messages.info(request, "This relation already exists.")
			return redirect("ticket_detail", pk=ticket.pk)
		# Also check the reverse direction
		if TicketRelation.objects.filter(
			subject=target, target=ticket, relation_type=relation_type
		).exists():
			messages.info(request, "This relation already exists.")
			return redirect("ticket_detail", pk=ticket.pk)
		TicketRelation.objects.create(
			subject=ticket,
			target=target,
			relation_type=relation_type,
		)
		messages.success(request, "Relation added.")
		return redirect("ticket_detail", pk=ticket.pk)
	return redirect("ticket_detail", pk=ticket.pk)


@login_required
def ticket_relation_delete(request, pk):
	"""Delete a relation."""
	relation = get_object_or_404(TicketRelation, pk=pk)
	# Ensure the relation's tickets are in the same project
	if relation.subject.project != relation.target.project:
		messages.error(request, "Cannot delete relation between tickets in different projects.")
		return redirect("ticket_detail", pk=relation.subject.pk)
	ticket = relation.subject
	if request.method == "POST":
		relation.delete()
		# Also delete the symmetric counterpart if it exists
		reverse_map = Ticket.RelationType._REVERSE_MAP or {}
		if relation.relation_type in reverse_map:
			try:
				TicketRelation.objects.get(
					subject=relation.target,
					target=relation.subject,
					relation_type=reverse_map[relation.relation_type],
				).delete()
			except TicketRelation.DoesNotExist:
				pass
		messages.success(request, "Relation removed.")
	return redirect("ticket_detail", pk=ticket.pk)


@login_required
def label_list(request, pk=None):
	"""List and manage labels for a project."""
	if pk is not None:
		project = get_object_or_404(Project, pk=pk)
	else:
		project_key = request.GET.get("project")
		if project_key:
			project = get_object_or_404(Project, key=project_key.upper())
		else:
			# No project specified — show all labels across all projects
			return render(request, "tracking/label_list.html", {
				"title": "Labels",
				"project": None,
				"labels": Label.objects.all().order_by("project__key", "name"),
				"projects": Project.objects.all(),
			})
	return render(request, "tracking/label_list.html", {
		"title": f"Labels — {project.key}",
		"project": project,
		"labels": project.labels.all().order_by("name"),
	})


@login_required
def label_create(request, pk):
	"""Create a new label for a project."""
	project = get_object_or_404(Project, pk=pk)
	if request.method == "POST":
		form = LabelForm(request.POST, project=project)
		if form.is_valid():
			label = form.save(commit=False)
			label.project = project
			label.save()
			messages.success(request, f"Label '{label.name}' created.")
			return redirect("label_list", pk=project.pk)
	else:
		form = LabelForm(project=project)

	return render(request, "tracking/label_form.html", {
		"title": f"New label — {project.key}",
		"form": form,
		"project": project,
	})


@login_required
def label_update(request, pk):
	"""Edit an existing label."""
	label = get_object_or_404(Label, pk=pk)
	if request.method == "POST":
		form = LabelForm(request.POST, instance=label, project=label.project)
		if form.is_valid():
			label = form.save()
			messages.success(request, f"Label '{label.name}' updated.")
			return redirect("label_list", pk=label.project.pk)
	else:
		form = LabelForm(instance=label, project=label.project)

	return render(request, "tracking/label_form.html", {
		"title": f"Edit label — {label.project.key}",
		"form": form,
		"project": label.project,
		"label": label,
	})


@login_required
def label_delete(request, pk):
	"""Delete a label."""
	label = get_object_or_404(Label, pk=pk)
	project = label.project
	if request.method == "POST":
		form = LabelDeleteForm(request.POST, project=project)
		if form.is_valid():
			selected_label = form.cleaned_data["label"]
			name = selected_label.name
			selected_label.delete()
			messages.success(request, f"Label '{name}' deleted.")
			return redirect("label_list", pk=project.pk)
	else:
		form = LabelDeleteForm(project=project)

	return render(request, "tracking/label_delete.html", {
		"title": f"Delete label — {project.key}",
		"form": form,
		"project": project,
		"label": label,
	})


@login_required
def component_list(request, pk=None):
	"""List and manage components for a project."""
	if pk is not None:
		project = get_object_or_404(Project, pk=pk)
	else:
		project_key = request.GET.get("project")
		if project_key:
			project = get_object_or_404(Project, key=project_key.upper())
		else:
			return render(request, "tracking/component_list.html", {
				"title": "Components",
				"project": None,
				"components": Component.objects.all().order_by("project__key", "name"),
				"projects": Project.objects.all(),
			})
	return render(request, "tracking/component_list.html", {
		"title": f"Components — {project.key}",
		"project": project,
		"components": project.components.all().order_by("name"),
	})


@login_required
def component_create(request, pk):
	"""Create a new component for a project."""
	project = get_object_or_404(Project, pk=pk)
	if request.method == "POST":
		form = ComponentForm(request.POST, project=project)
		if form.is_valid():
			component = form.save(commit=False)
			component.project = project
			component.save()
			messages.success(request, f"Component '{component.name}' created.")
			return redirect("component_list", pk=project.pk)
	else:
		form = ComponentForm(project=project)

	return render(request, "tracking/component_form.html", {
		"title": f"New component — {project.key}",
		"form": form,
		"project": project,
	})


@login_required
def component_update(request, pk):
	"""Edit an existing component."""
	component = get_object_or_404(Component, pk=pk)
	if request.method == "POST":
		form = ComponentForm(request.POST, instance=component, project=component.project)
		if form.is_valid():
			component = form.save()
			messages.success(request, f"Component '{component.name}' updated.")
			return redirect("component_list", pk=component.project.pk)
	else:
		form = ComponentForm(instance=component, project=component.project)

	return render(request, "tracking/component_form.html", {
		"title": f"Edit component — {component.project.key}",
		"form": form,
		"project": component.project,
		"component": component,
	})


@login_required
def component_delete(request, pk):
	"""Delete a component."""
	component = get_object_or_404(Component, pk=pk)
	project = component.project
	if request.method == "POST":
		form = ComponentDeleteForm(request.POST, project=project)
		if form.is_valid():
			selected_component = form.cleaned_data["component"]
			name = selected_component.name
			selected_component.delete()
			messages.success(request, f"Component '{name}' deleted.")
			return redirect("component_list", pk=project.pk)
	else:
		form = ComponentDeleteForm(project=project)

	return render(request, "tracking/component_delete.html", {
		"title": f"Delete component — {project.key}",
		"form": form,
		"project": project,
		"component": component,
	})


@login_required
def ticket_attachment_upload(request, pk):
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == "POST":
		form = AttachmentForm(request.POST, request.FILES)
		if form.is_valid():
			attachment = form.save(commit=False)
			attachment.ticket = ticket
			_, ext = attachment.name.rsplit(".", 1) if "." in attachment.name else (attachment.name, "")
			attachment.mime_type = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
				"pdf": "application/pdf", "txt": "text/plain", "log": "text/plain",
				"json": "application/json"}.get(ext.lower(), "application/octet-stream")
			attachment.save()
			messages.success(request, "Attachment uploaded.")
			return redirect("ticket_detail", pk=ticket.pk)
	return redirect("ticket_detail", pk=ticket.pk)


@login_required
@require_POST
def ticket_attachment_delete(request, pk):
	attachment = get_object_or_404(Attachment, pk=pk)
	ticket = attachment.ticket
	attachment.file.delete()
	attachment.delete()
	messages.success(request, "Attachment deleted.")
	return redirect("ticket_detail", pk=ticket.pk)


@login_required
def ticket_attachment_serve(request, pk, attachment_pk):
	attachment = get_object_or_404(Attachment, pk=attachment_pk)
	try:
		with open(attachment.file.path, "rb") as f:
			response = HttpResponse(f.read(), content_type=attachment.mime_type)
		response["Content-Disposition"] = f'inline; filename="{attachment.name}"'
		return response
	except (FileNotFoundError, ValueError) as e:
		messages.error(request, "Attachment file not found.")
		return redirect("ticket_detail", pk=attachment.ticket.pk)
