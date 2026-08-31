from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from . import _common as api
from tracking.models import Ticket, TicketRelation
from tracking.forms import WorkLogForm
from tracking.queryset_helpers import build_ticket_queryset

@api.require_http_methods(['GET', 'POST'])
@csrf_exempt
def collection(request):
	if request.method == 'GET':
		qs = build_ticket_queryset(request, labels_by_id=True, components_by_id=True)
		# API-specific annotations for serialization.
		qs = qs.prefetch_related('child_tickets', 'labels', 'components').annotate(
			issue_count=Count('child_tickets')
		)
		return api._page_json(request, qs)
	elif request.method == 'POST':
		data = api.parse_json(request)
		# Convert project key to ID
		project_key = data.pop('project', None)
		if project_key:
			from tracking.models import Project
			p = Project.objects.filter(key=project_key).first()
			if p:
				data['project_id'] = p.pk
			else:
				return JsonResponse({'project': ['Project not found']}, status=404)
		from tracking.models import Label, Component
		label_names = data.pop('labels', [])
		component_names = data.pop('components', [])
		ticket = Ticket.objects.create(**{k: v for k, v in data.items() if k not in ('labels', 'components')})
		if label_names:
			for name in label_names:
				label = Label.objects.filter(project=ticket.project, name=name).first()
				if label:
					ticket.labels.add(label)
		if component_names:
			for name in component_names:
				component = Component.objects.filter(project=ticket.project, name=name).first()
				if component:
					ticket.components.add(component)
		return JsonResponse(ticket._data(), status=201)
	return JsonResponse({'error': 'Unsupported method'}, status=405)

@api.require_http_methods(['POST'])
@csrf_exempt
def transition(request, pk):
	ticket = Ticket.objects.select_related('project').filter(pk=pk).first()
	if not ticket:
		return JsonResponse({'error': 'Not found'}, status=404)
	data = api.parse_json(request)
	if 'state' not in data:
		return JsonResponse({'error': 'state is required'}, status=400)
	next_state = data['state']
	if next_state not in ticket.allowed_transitions():
		return JsonResponse({
			'error': f'Cannot transition to {Ticket.State(next_state)}',
			'allowed_transitions': list(ticket.allowed_transitions())
		}, status=409)
	ticket.state = next_state
	ticket.save(update_fields=['state', 'updated_at'])
	return JsonResponse(ticket._data())

@api.require_http_methods(["GET", "POST"])
@csrf_exempt
def api_ticket_worklog_collection(request, pk):
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == "GET":
		entries = ticket.worklog_entries.all()
		page = int(request.GET.get("page", 1))
		page_size = min(int(request.GET.get("page_size", 25)), 100)
		paginator = Paginator(entries, page_size)
		page_obj = paginator.get_page(page)
		data = []
		for entry in page_obj:
			data.append({
				"id": entry.pk,
				"author": entry.author.get_full_name() or entry.author.username,
				"time_spent": entry.time_spent,
				"original_estimate": entry.original_estimate,
				"remaining_estimate": entry.remaining_estimate,
				"date": entry.date.isoformat(),
				"comment": entry.comment,
				"created_at": entry.created_at.isoformat(),
			})
		return JsonResponse({
			"count": paginator.count,
			"pagination": {
				"next": paginator.get_page(page).has_next() and f"/tracking/api/tickets/{pk}/worklogs/?page={page+1}&page_size={page_size}" or None,
				"previous": paginator.get_page(page).has_previous() and f"/tracking/api/tickets/{pk}/worklogs/?page={page-1}&page_size={page_size}" or None,
			},
			"results": data,
		})
	elif request.method == "POST":
		data = api.parse_json(request)
		form = WorkLogForm(data=data)
		if form.is_valid():
			entry = form.save(commit=False)
			entry.ticket = ticket
			entry.author = request.user
			entry.save()
			return JsonResponse({
				"id": entry.pk,
				"time_spent": entry.time_spent,
				"original_estimate": entry.original_estimate,
				"remaining_estimate": entry.remaining_estimate,
				"date": entry.date.isoformat(),
			}, status=201)
		return JsonResponse({"error": dict(form.errors)}, status=400)


@api.require_http_methods(['GET', 'PATCH'])
@csrf_exempt
def detail(request, pk):
	ticket = Ticket.objects.select_related('sprint', 'parent_epic', 'assignee', 'project').filter(pk=pk).first()
	if not ticket:
		return JsonResponse({'error': 'Not found'}, status=404)
	if request.method == 'GET':
		data = ticket._data()
		data['comments_count'] = ticket.comments.count()
		data['attachments_count'] = ticket.attachments.count()
		data['relations_count'] = ticket.relations.count()
		data['watchers_count'] = ticket.watchers.count()
		data['subtasks_count'] = ticket.child_tickets.count()
		data['sprint_name'] = ticket.sprint.name if ticket.sprint else 'Backlog'
		data['project_key'] = ticket.project.key
		# Time-tracking rollups
		data['total_original_estimate'] = ticket.total_original_estimate
		data['total_spent_time'] = ticket.total_spent
		data['total_remaining_estimate'] = ticket.total_remaining_estimate
		data['progress_percent'] = ticket.progress_percent
		return JsonResponse(data)
	elif request.method == 'PATCH':
		data = api.parse_json(request)
		state = data.get('state')
		if state:
			return JsonResponse({'error': 'State transitions must use the /transition/ endpoint.'}, status=400)
		updatable = ['title', 'description', 'priority', 'assignee', 'due_date', 'estimation', 'sprint']
		for field in updatable:
			if field in data:
				setattr(ticket, field, data[field])
		if 'parent_epic' in data:
			pe_id = data['parent_epic']
			if pe_id:
				ticket.parent_epic = get_object_or_404(Ticket, pk=pe_id)
			else:
				ticket.parent_epic = None
		if 'labels' in data:
			label_names = data['labels']
			ticket.labels.clear()
			from tracking.models import Label
			for name in label_names:
				label = Label.objects.filter(project=ticket.project, name=name).first()
				if label:
					ticket.labels.add(label)
		if 'components' in data:
			component_names = data['components']
			ticket.components.clear()
			from tracking.models import Component
			for name in component_names:
				component = Component.objects.filter(project=ticket.project, name=name).first()
				if component:
					ticket.components.add(component)
		ticket.save(update_fields=[f for f in updatable if f in data] + (['parent_epic'] if 'parent_epic' in data else []))
		return JsonResponse(ticket._data())
	return JsonResponse({'error': 'Unsupported method'}, status=405)

@api.require_http_methods(['POST'])
@csrf_exempt
def ticket_relations_add(request, id):
	ticket = Ticket.objects.filter(pk=id).first()
	if not ticket:
		return JsonResponse({'error': 'Not found'}, status=404)
	data = api.parse_json(request)
	target_pk = data.get('target_id')
	relation_type = data.get('type', 'related_to')
	if not target_pk:
		return JsonResponse({'error': 'target_id is required'}, status=400)
	target = Ticket.objects.filter(pk=target_pk).first()
	if not target:
		return JsonResponse({'error': 'Target ticket not found'}, status=404)
	if ticket.project != target.project:
		return JsonResponse({'error': 'Tickets must be in the same project'}, status=400)
	if ticket.pk == target.pk:
		return JsonResponse({'error': 'A ticket cannot be related to itself'}, status=400)
	if relation_type not in Ticket.RelationType.values:
		return JsonResponse({
			'error': 'Invalid relation type',
			'allowed_types': list(Ticket.RelationType.values),
		}, status=400)
	relation = TicketRelation(subject=ticket, target=target, relation_type=relation_type)
	try:
		relation.full_clean()
	except ValidationError as exc:
		return JsonResponse({'error': 'Relation not allowed', 'detail': exc.messages}, status=409)
	relation.save()
	return JsonResponse({
		'id': relation.pk,
		'subject': ticket.pk,
		'target': target.pk,
		'type': relation.relation_type,
	}, status=201)

@api.require_http_methods(['DELETE'])
@csrf_exempt
def ticket_relations_delete(request, pk):
	relation = TicketRelation.objects.filter(pk=pk).first()
	if not relation:
		return JsonResponse({'error': 'Not found'}, status=404)
	relation.delete()
	return JsonResponse({'deleted': pk})
