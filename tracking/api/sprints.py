from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from . import _common as api
from tracking.models import Sprint, Project
from tracking.forms import SprintForm

@api.require_http_methods(['GET'])
def list_sprints(request, key):
	project = get_object_or_404(Project, key=key)
	return api._page_json(request, project.sprints.all())

@api.require_http_methods(['POST'])
def create_sprint(request, key):
	project = get_object_or_404(Project, key=key)
	form = SprintForm(request.POST)
	if form.is_valid():
		sprint = form.save(commit=False)
		sprint.project = project
		sprint.save()
		return JsonResponse(sprint._data(), status=201)
	return JsonResponse(form.errors, status=400)

@api.require_http_methods(['GET', 'PATCH', 'DELETE'])
def detail(request, pk):
	sprint = get_object_or_404(Sprint, pk=pk)
	if request.method == 'GET':
		return JsonResponse(sprint._data())
	elif request.method == 'PATCH':
		form = SprintForm(request.POST, instance=sprint)
		if form.is_valid():
			form.save()
			return JsonResponse(sprint._data())
		return JsonResponse(form.errors, status=400)
	elif request.method == 'DELETE':
		if sprint.is_backlog:
			return JsonResponse({'error': 'Cannot delete backlog sprint'}, status=405)
		sprint.delete()
		return JsonResponse({'deleted': pk})
	return JsonResponse({'error': 'Unsupported method'}, status=405)

@api.require_http_methods(['POST'])
def close_sprint(request, key, pk):
	project = get_object_or_404(Project, key=key)
	sprint = get_object_or_404(Sprint, pk=pk, project=project)
	body = request.body
	try:
		import json
		data = json.loads(body)
	except json.JSONDecodeError:
		data = {}
	action = data.get('action', 'backlog')
	target_id = data.get('target_sprint') or data.get('target_sprint_id')
	if action == 'sprint' and not target_id:
		return JsonResponse({'error': 'target_sprint is required when action is sprint'}, status=400)
	if action == 'sprint':
		target = get_object_or_404(Sprint, pk=target_id)
		if target.project != project:
			return JsonResponse({'error': 'Target sprint must belong to the same project'}, status=404)
		if target.pk == sprint.pk:
			return JsonResponse({'error': 'Cannot move tickets to the same sprint'}, status=400)
	sprint.close_with_action(action, target_id)
	sprint.refresh_from_db()
	return JsonResponse(sprint._data())
