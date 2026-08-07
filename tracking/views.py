from django.shortcuts import render

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from .forms import CommentForm, ProjectForm, TicketForm, TicketTransitionForm
from .models import Comment, Component, Flag, Project, Ticket


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

	return render(request, "tracking/dashboard.html", {
		"title": "Dashboard",
		"total_tickets": total_tickets,
		"open_tickets": open_tickets,
		"project_count": Project.objects.count(),
		"critical_count": priority_counts.get(Ticket.Priority.CRITICAL.value, 0),
		"state_breakdown": state_breakdown,
		"recent_tickets": recent_tickets,
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
	"""List tickets, optionally filtered by project, state, component, and flag."""
	tickets = Ticket.objects.select_related("project", "assignee")

	project_key = request.GET.get("project")
	if project_key:
		tickets = tickets.filter(project__key=project_key)

	state = request.GET.get("state")
	if state:
		tickets = tickets.filter(state=state)

	component = request.GET.get("component")
	if component:
		tickets = tickets.filter(components__name=component)

	flag = request.GET.get("flag")
	if flag:
		tickets = tickets.filter(flags__name=flag)

	return render(request, "tracking/ticket_list.html", {
		"title": "Tickets",
		"tickets": tickets,
		"projects": Project.objects.all(),
		"states": Ticket.State.choices,
		"current_project": project_key or "",
		"current_state": state or "",
		"current_component": component or "",
		"current_flag": flag or "",
		"components": Component.objects.all().order_by("name"),
		"flags": Flag.objects.all().order_by("name"),
	})


@login_required
def ticket_detail(request, pk):
	"""Show a single ticket with its allowed state transitions and comments."""
	ticket = get_object_or_404(
		Ticket.objects.select_related("project", "assignee", "reporter"), pk=pk
	)
	comments = ticket.comments.select_related("author").all()
	return render(request, "tracking/ticket_detail.html", {
		"title": ticket.title,
		"ticket": ticket,
		"transition_form": TicketTransitionForm(ticket=ticket),
		"comment_form": CommentForm(),
		"comments": comments,
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
		# Pre-populate components/flags for the selected project
		project_key = request.GET.get("project")
		if project_key:
			form.fields["components"].queryset = Component.objects.filter(
				project__key=project_key.upper()
			)
			form.fields["flags"].queryset = Flag.objects.filter(
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
