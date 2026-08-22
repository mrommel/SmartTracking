import json
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from tracking.models import Ticket, Sprint, Comment, Attachment, Label, Component, SavedFilter
from tracking.forms import TicketForm, TicketTransitionForm, CommentForm, AttachmentForm
from django.http import JsonResponse, HttpResponseForbidden, FileResponse
from django.db.models import Q

# Mapping of sort fields to database columns and priority ordering
SORT_MAP = {
	'title': 'title',
	'type': 'type',
	'priority': 'priority',
	'state': 'state',
	'due_date': 'due_date',
	'created': 'created_at',
	'updated': 'updated_at',
}

PRIORITY_ORDER = {
	'CRITICAL': 0,
	'HIGH': 1,
	'MEDIUM': 2,
	'LOW': 3,
}


@login_required
def ticket_list(request, project_key: str = None):
	if project_key:
		qs = Ticket.objects.filter(project__key=project_key).select_related('sprint', 'parent_epic', 'assignee')
	else:
		qs = Ticket.objects.all().select_related('sprint', 'parent_epic', 'assignee')

	# Multi-value filters
	if request.GET.getlist('state'):
		qs = qs.filter(state__in=request.GET.getlist('state'))
	if request.GET.getlist('label'):
		for label_name in request.GET.getlist('label'):
			qs = qs.filter(labels__name=label_name)
	if request.GET.getlist('component'):
		for comp_name in request.GET.getlist('component'):
			qs = qs.filter(components__name=comp_name)

	# Single-value filters
	project = request.GET.get('project')
	if project:
		qs = qs.filter(project__key=project)

	# Assignee filter (supports multi-value via getlist)
	assignee_values = request.GET.getlist('assignee')
	if 'me' in assignee_values:
		qs = qs.filter(assignee=request.user)
	elif 'unassigned' in assignee_values:
		qs = qs.filter(assignee__isnull=True)
	elif assignee_values:
		numeric_ids = [aid for aid in assignee_values if aid.isdigit()]
		if numeric_ids:
			qs = qs.filter(assignee_id__in=numeric_ids)

	# Query filter – search title, description, or numeric ticket ID
	query = request.GET.get('query') or request.GET.get('q')
	if query:
		# Try matching by numeric ticket ID first
		if query.isdigit():
			qs = qs.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(pk=int(query)))
		else:
			qs = qs.filter(Q(title__icontains=query) | Q(description__icontains=query))

	# Sorting
	sort_field = request.GET.get('sort', 'created_at')
	order = request.GET.get('order', 'desc')
	db_field = SORT_MAP.get(sort_field, 'created_at')
	if sort_field == 'priority':
		# Custom priority ordering (IntegerChoices: LOW=1, MEDIUM=2, HIGH=3, CRITICAL=4)
		# "desc" priority = CRITICAL first (ascending numeric sort)
		from django.db.models import Case, When, Value, IntegerField
		priority_map = {
			Ticket.Priority.CRITICAL: 0,
			Ticket.Priority.HIGH: 1,
			Ticket.Priority.MEDIUM: 2,
			Ticket.Priority.LOW: 3,
		}
		annotated = qs.annotate(
			priority_sort=Case(
				*[When(priority=p, then=v) for p, v in priority_map.items()],
				default=4,
				output_field=IntegerField(),
			)
		)
		ordering = ('priority_sort',) if order == 'desc' else ('-priority_sort',)
		annotated = annotated.order_by(*ordering)
	else:
		ordering = (f'-{db_field}' if order == 'desc' else db_field,)
		annotated = qs.order_by(*ordering)

	# Context data for bulk actions
	all_sprints = Sprint.objects.all().order_by('order')
	sprints_json = json.dumps([(s.pk, s.name) for s in all_sprints])
	all_labels = Label.objects.all().order_by('name')
	labels_json = json.dumps([(l.pk, l.name) for l in all_labels])
	all_components = Component.objects.all().order_by('name')
	components_json = json.dumps([(c.pk, c.name) for c in all_components])

	# State choices for bulk transition
	state_choices = [(s, s.label) for s in Ticket.State]

	# Active filter pills
	active_states = request.GET.getlist('state')
	# active_labels will be resolved from Label model instances in the template context
	active_labels = list(Label.objects.filter(name__in=request.GET.getlist('label')))
	# active_components will be resolved from Component model instances
	active_components = list(Component.objects.filter(name__in=request.GET.getlist('component')))
	# pagination_params for preserving filters across pagination
	pagination_params = [f"{k}={v}" for k, v in request.GET.items() if k != 'page']
	# Save query params to session for saved filter creation
	request.session['last_ticket_list_query'] = dict(request.GET)
	request.session['last_ticket_list_query'].pop('page', None)
	# saved filters for the current user/project
	saved_filters = SavedFilter.objects.filter(user=request.user)
	if project_key:
		saved_filters = saved_filters.filter(project__key=project_key)

	return render(request, 'tracking/ticket_list.html', {
		'tickets': annotated,
		'order': order,
		'sort': sort_field,
		'sprints_json': sprints_json,
		'labels_json': labels_json,
		'components_json': components_json,
		'state_choices': state_choices,
		'bulk_assignee_choices': [],
		'active_states': active_states,
		'active_labels': active_labels,
		'active_components': active_components,
		'pagination_params': pagination_params,
		'saved_filters': saved_filters,
	})


@login_required
def ticket_delete(request, project_pk, pk):
	try:
		ticket = Ticket.objects.get(pk=pk, project_id=project_pk)
	except Ticket.DoesNotExist:
		messages.warning(request, 'Ticket not found or you do not have permission to delete it.')
		return redirect('ticket_list')
	if request.method == 'POST':
		ticket.delete()
		messages.success(request, 'Ticket deleted successfully.')
		return redirect('ticket_list')
	return render(request, 'tracking/ticket_delete.html', {'ticket': ticket})


@login_required
def ticket_detail(request, pk):
	ticket = get_object_or_404(Ticket.objects.select_related('sprint', 'parent_epic', 'assignee'), pk=pk)
	attachments = list(ticket.attachments.all())
	image_attachments = [a for a in attachments if a.is_image]
	non_image_attachments = [a for a in attachments if not a.is_image]
	return render(request, 'tracking/ticket_detail.html', {
		'ticket': ticket,
		'attachments': attachments,
		'image_attachments': image_attachments,
		'non_image_attachments': non_image_attachments,
		'transition_form': TicketTransitionForm(ticket=ticket),
		'sprint_form': TicketForm(initial={'sprint': ticket.sprint.pk}) if ticket.sprint else TicketForm(),
		'	comment_form': CommentForm(),
		'child_tickets': ticket.child_tickets.all(),
		'comments': Paginator(ticket.comments.all().order_by('created_at'), 20).page(
			int(request.GET.get('comments_page', 1))
		),
		'sprints': Sprint.objects.filter(project=ticket.project),
	})


@login_required
def ticket_transition(request, pk):
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == 'POST':
		form = TicketTransitionForm(request.POST, ticket=ticket)
		if form.is_valid():
			new_state = form.cleaned_data['state']
			if ticket.can_transition_to(new_state):
				ticket.state = new_state
				ticket.save(update_fields=['state', 'updated_at'])
				return redirect('ticket_detail', pk=pk)
			else:
				form.add_error('state', 'Invalid transition')
	else:
		form = TicketTransitionForm(ticket=ticket)
	return render(request, 'tracking/ticket_transition.html', {
		'ticket': ticket,
		'form': form,
	})


@login_required
def ticket_sprint_assign(request, pk):
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == 'POST':
		sprint_id = request.POST.get('sprint')
		if sprint_id:
			sprint = get_object_or_404(Sprint, pk=sprint_id)
			ticket.sprint = sprint
		else:
			ticket.sprint = None
		ticket.save(update_fields=['sprint', 'updated_at'])
		return redirect('ticket_detail', pk=pk)
	return redirect('ticket_detail', pk=pk)


@login_required
def ticket_create(request):
	if request.method == 'POST':
		form = TicketForm(request.POST)
		if form.is_valid():
			ticket = form.save(commit=False)
			ticket.reporter = request.user
			ticket.save()
			form.save_m2m()
			messages.success(request, 'Ticket created')
			return redirect('ticket_detail', pk=ticket.pk)
	else:
		form = TicketForm()
	return render(request, 'tracking/ticket_create.html', {'form': form})


@login_required
def ticket_edit(request, pk):
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == 'POST':
		form = TicketForm(request.POST, instance=ticket)
		if form.is_valid():
			form.save()
			messages.success(request, 'Ticket updated')
			return redirect('ticket_detail', pk=pk)
	else:
		form = TicketForm(instance=ticket)
	return render(request, 'tracking/ticket_edit.html', {'form': form, 'ticket': ticket})


@login_required
def ticket_relation_add(request, pk):
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == 'POST':
		target_pk = request.POST.get('target_ticket')
		relation_type = request.POST.get('relation_type')
		if not target_pk or not relation_type:
			messages.warning(request, 'Missing required fields')
			return redirect('ticket_detail', pk=pk)
		try:
			target = Ticket.objects.get(pk=target_pk)
		except Ticket.DoesNotExist:
			messages.warning(request, 'Selected ticket does not exist')
			return redirect('ticket_detail', pk=pk)
		if ticket.project != target.project:
			messages.warning(request, 'Can only relate tickets within the same project')
			return redirect('ticket_detail', pk=pk)
		from tracking.models import TicketRelation
		# Check for duplicate or reverse
		if TicketRelation.objects.filter(
			subject=ticket, target=target, relation_type=relation_type
		).exists():
			messages.warning(request, 'Relation already exists')
			return redirect('ticket_detail', pk=pk)
		if TicketRelation.objects.filter(
			subject=target, target=ticket, relation_type=relation_type
		).exists():
			messages.warning(request, 'Reverse relation already exists')
			return redirect('ticket_detail', pk=pk)
		rel = TicketRelation.objects.create(
			subject=ticket, target=target, relation_type=relation_type
		)
		messages.success(request, 'Relation added')
		return redirect('ticket_detail', pk=pk)
	return redirect('ticket_detail', pk=pk)


@login_required
def ticket_relation_delete(request, pk):
	from tracking.models import TicketRelation
	rel = get_object_or_404(TicketRelation, pk=pk)
	ticket_pk = rel.subject.pk
	rel.delete()
	messages.success(request, 'Relation deleted')
	return redirect('ticket_detail', pk=ticket_pk)


@login_required
def ticket_comment_create(request, pk):
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == 'POST':
		form = CommentForm(request.POST)
		if form.is_valid():
			comment = form.save(commit=False)
			comment.ticket = ticket
			comment.author = request.user
			comment.save()
			messages.success(request, 'Comment added')
			return redirect('ticket_detail', pk=pk)
		else:
			messages.warning(request, 'Comment body cannot be empty.')
			return redirect('ticket_detail', pk=pk)
	else:
		form = CommentForm()
	return render(request, 'tracking/ticket_detail.html', {
		'ticket': ticket,
		'comment_form': form,
	})


@login_required
def ticket_comment_edit(request, pk):
	comment = get_object_or_404(Comment, pk=pk)
	if request.method == 'POST':
		form = CommentForm(request.POST, instance=comment)
		if form.is_valid():
			form.save()
			messages.success(request, 'Comment updated')
		return redirect('ticket_detail', pk=comment.ticket.pk)
	return redirect('ticket_detail', pk=comment.ticket.pk)


@login_required
def ticket_comment_delete(request, pk):
	comment = get_object_or_404(Comment, pk=pk)
	ticket_pk = comment.ticket.pk
	if request.method == 'POST':
		comment.delete()
		messages.success(request, 'Comment deleted')
		return redirect('ticket_detail', pk=ticket_pk)
	return render(request, 'tracking/comment_delete.html', {'comment': comment})


@login_required
def ticket_attachment_upload(request, pk):
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == 'POST':
		form = AttachmentForm(request.POST, request.FILES)
		if form.is_valid():
			attachment = form.save(commit=False)
			attachment.ticket = ticket
			attachment.uploaded_by = request.user
			attachment.save()
			messages.success(request, "Attachment uploaded")
			return redirect('ticket_detail', pk=pk)
	else:
		form = AttachmentForm()
	return render(request, 'tracking/attachment_upload.html', {'form': form, 'ticket': ticket})


@login_required
def ticket_attachment_serve(request, pk, attachment_pk):
	attachment = get_object_or_404(Attachment, pk=attachment_pk)
	if attachment.ticket.pk != pk:
		return HttpResponseForbidden()
	response = FileResponse(attachment.file)
	response['Content-Type'] = attachment.mime_type
	return response


@login_required
def ticket_attachment_delete(request, pk):
	attachment = get_object_or_404(Attachment, pk=pk)
	if request.method == 'POST':
		ticket_pk = attachment.ticket.pk
		attachment.delete()
		messages.success(request, 'Attachment deleted')
	return redirect('ticket_detail', pk=ticket_pk)


@login_required
def update_backlog_order(request):
	# Handle drag-and-drop order updates
	if request.method == 'POST':
		ticket_ids = request.POST.getlist('ticket_ids')
		for idx, tid in enumerate(ticket_ids):
			try:
				ticket = Ticket.objects.get(pk=tid)
				ticket.order = idx
				ticket.save(update_fields=['order'])
			except Ticket.DoesNotExist:
				pass
	return redirect('ticket_list')
