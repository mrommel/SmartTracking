from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from . import _common as api
from tracking.models import Ticket, Watcher
from django.contrib.auth import get_user_model

User = get_user_model()

@api.require_http_methods(['GET', 'POST'])
def detail(request, ticket_pk):
	ticket = Ticket.objects.select_related('project').filter(pk=ticket_pk).first()
	if not ticket:
		return JsonResponse({'error': 'Not found'}, status=404)
	if request.method == 'GET':
		watchers = Watcher.objects.filter(ticket=ticket).select_related('user')
		results = [
			{'id': w.pk, 'username': w.user.username, 'ticket': ticket_pk, 'user_id': w.user_id}
			for w in watchers
		]
		return JsonResponse({
			'count': len(results),
			'pagination': {'next': None, 'previous': None},
			'watchers': results,
		})
	elif request.method == 'POST':
		data = api.parse_json(request)
		user_id = data.get('user_id') or request.POST.get('user_id')
		if not user_id:
			return JsonResponse({'error': 'user_id is required'}, status=400)
		user = User.objects.filter(pk=user_id).first()
		if not user:
			return JsonResponse({'error': 'User not found'}, status=400)
		watcher, created = Watcher.objects.get_or_create(ticket=ticket, user=user)
		if not created:
			return JsonResponse({'status': 'already_watching'})
		return JsonResponse({'status': 'added'})

@api.require_http_methods(['DELETE'])
def remove(request, ticket_pk, user_pk):
	ticket = get_object_or_404(Ticket, pk=ticket_pk)
	watcher = get_object_or_404(Watcher, ticket=ticket, user=user_pk)
	watcher.delete()
	return JsonResponse({'status': 'removed'})

@api.require_http_methods(['GET'])
def workspace_list(request):
	watchers = Watcher.objects.select_related('ticket__project', 'user').filter(user=request.user)
	results = [
		{'id': w.pk, 'username': w.user.username, 'ticket': w.ticket.pk, 'ticket_title': w.ticket.title, 'user_id': w.user_id}
		for w in watchers
	]
	return JsonResponse({
		'count': len(results),
		'pagination': {'next': None, 'previous': None},
		'watchers': results,
	})

@api.require_http_methods(['POST'])
def workspace_add(request):
	data = api.parse_json(request)
	ticket_id = data.get('ticket_id') or request.POST.get('ticket_id')
	if not ticket_id:
		return JsonResponse({'error': 'ticket_id is required'}, status=400)
	ticket = Ticket.objects.filter(pk=ticket_id).first()
	if not ticket:
		return JsonResponse({'error': 'Ticket not found'}, status=404)
	watcher, created = Watcher.objects.get_or_create(ticket=ticket, user=request.user)
	if not created:
		return JsonResponse({'status': 'already_watching'})
	return JsonResponse({'status': 'added'})

@api.require_http_methods(['DELETE'])
def workspace_remove(request, pk):
	watcher = get_object_or_404(Watcher, pk=pk)
	watcher.delete()
	return JsonResponse({'deleted': pk})