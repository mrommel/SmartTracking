from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.core.paginator import Paginator
from django.contrib.auth import get_user_model
from . import _common as api
from . import _common
from tracking.models import Ticket, Comment, Attachment, Sprint, WorkLog
from tracking.forms import TicketForm, WorkLogForm
import json

@api.require_http_methods(['GET', 'POST'])
@csrf_exempt
def collection(request):
	if request.method == 'GET':
		qs = Ticket.objects.all().select_related('sprint', 'parent_epic', 'assignee').prefetch_related(
			'child_tickets', 'labels', 'components'
		).annotate(issue_count=Count('child_tickets'))
		project = request.GET.get('project', '')
		if project: qs = qs.filter(project__key=project)
		state = request.GET.getlist('state')
		if state: qs = qs.filter(state__in=state)
		assignee = request.GET.get('assignee', '')
		if assignee:
			if assignee == 'me':
				qs = qs.filter(assignee=request.user)
			elif assignee == 'unassigned':
				qs = qs.filter(assignee__isnull=True)
			elif assignee.isdigit():
				qs = qs.filter(assignee__pk=int(assignee))
		component = request.GET.getlist('component')
		if component: qs = qs.filter(components__id__in=component)
		label = request.GET.getlist('label')
		if label: qs = qs.filter(labels__id__in=label)
		q = request.GET.get('q', '').strip()
		if q: qs = qs.filter(title__icontains=q) | qs.filter(description__icontains=q)
		sort_map = {
			'title': 'title', 'type': 'type', 'priority': 'priority',
			'state': 'state', 'due_date': 'due_date', 'created_at': 'created_at',
			'updated_at': 'updated_at'
		}
		order = request.GET.get('order', '-created_at')
		sort_field = request.GET.get('sort', '')
		if sort_field in sort_map:
			pref = '-' if order == 'desc' else ''
			qs = qs.order_by(f'{pref}{sort_map[sort_field]}')
		qs = qs.distinct()
		return api._page_json(request, qs)
	elif request.method == 'POST':
		body = request.body
		try:
			data = json.loads(body)
		except json.JSONDecodeError:
			data = {}
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
	body = request.body
	try:
		data = json.loads(body)
	except json.JSONDecodeError:
		return JsonResponse({'error': 'Invalid JSON'}, status=400)
	next_state = data.get('state')
	if not next_state:
		return JsonResponse({'error': 'state is required'}, status=400)
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
		try:
			body = json.loads(request.body)
		except (json.JSONDecodeError, ValueError):
			return JsonResponse({"error": "Invalid JSON"}, status=400)
		form = WorkLogForm(data=body)
		if form.is_valid():
			entry = form.save(commit=False)
			entry.ticket = ticket
			entry.author = request.user
			entry.save()
			return JsonResponse({"id": entry.pk, "time_spent": entry.time_spent, "date": entry.date.isoformat()}, status=201)
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
		return JsonResponse(data)
	elif request.method == 'PATCH':
		body = request.body
		try:
			data = json.loads(body)
		except json.JSONDecodeError:
			return JsonResponse({'error': 'Invalid JSON'}, status=400)
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
	if request.method == 'POST':
		body = request.body
		try:
			data = json.loads(body)
		except json.JSONDecodeError:
			return JsonResponse({'error': 'Invalid JSON'}, status=400)
		target_pk = data.get('target_id')
		relation_type = data.get('type', 'related_to')
		if not target_pk:
			return JsonResponse({'error': 'target_id is required'}, status=400)
		target = Ticket.objects.filter(pk=target_pk).first()
		if not target:
			return JsonResponse({'error': 'Target ticket not found'}, status=404)
		if ticket.project != target.project:
			return JsonResponse({'error': 'Tickets must be in the same project'}, status=400)
		from tracking.models import TicketRelation
		relation = TicketRelation.objects.create(subject=ticket, target=target, relation_type=relation_type)
		return JsonResponse({'id': relation.pk, 'type': relation.type}, status=201)
	return JsonResponse({'error': 'Unsupported method'}, status=405)

@api.require_http_methods(['DELETE'])
@csrf_exempt
def ticket_relations_delete(request, pk):
	from tracking.models import TicketRelation
	relation = TicketRelation.objects.filter(pk=pk).first()
	if not relation:
		return JsonResponse({'error': 'Not found'}, status=404)
	relation.delete()
	return JsonResponse({'deleted': pk})
