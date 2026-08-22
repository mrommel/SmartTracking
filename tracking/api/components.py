from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from . import _common as api
from tracking.models import Component, Project
import json

@api.require_http_methods(['GET', 'POST'])
def collection(request):
	project_key = request.GET.get('project', '')
	if project_key:
		qs = Project.objects.filter(key=project_key).first().components.all() if Project.objects.filter(key=project_key).first() else Component.objects.none()
	else:
		qs = Component.objects.none()
	if request.method == 'GET':
		return api._page_json(request, qs)
	elif request.method == 'POST':
		form = ComponentForm(request.POST)
		if form.is_valid():
			component = form.save()
			return JsonResponse(component._data(), status=201)
		return JsonResponse(form.errors, status=400)
	return JsonResponse({'error': 'Unsupported method'}, status=405)

@api.require_http_methods(['GET', 'PATCH', 'DELETE'])
def detail(request, pk):
	component = get_object_or_404(Component, pk=pk)
	if request.method == 'GET':
		return JsonResponse(component._data())
	elif request.method == 'PATCH':
		body = request.body
		try:
			data = json.loads(body) if body else {}
		except json.JSONDecodeError:
			data = {}
		for field in ['name', 'description']:
			if field in data:
				setattr(component, field, data[field])
		component.save(update_fields=[f for f in ['name', 'description'] if f in data])
		return JsonResponse(component._data())
	elif request.method == 'DELETE':
		component.delete()
		return JsonResponse({'status': 'deleted'})
	return JsonResponse({'error': 'Unsupported method'}, status=405)