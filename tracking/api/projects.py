from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import IntegrityError
from . import _common as api
from tracking.models import Project
from tracking.forms import ProjectForm

@api.require_http_methods(['GET', 'POST'])
@api.require_api_auth
def collection(request):
	if request.method == 'GET':
		return api._page_json(request, Project.objects.all())
	elif request.method == 'POST':
		data = api.parse_json(request)
		key = data.get('key', '').upper()
		if key and Project.objects.filter(key=key).exists():
			return JsonResponse({'key': ['Project with this key already exists']}, status=409)
		form = ProjectForm(data)
		if form.is_valid():
			try:
				project = form.save()
				return JsonResponse(project._data(), status=201)
			except IntegrityError:
				return JsonResponse({'key': ['Project with this key already exists']}, status=409)
		return JsonResponse(form.errors, status=400)
	return JsonResponse({'error': 'Unsupported method'}, status=405)

@api.require_http_methods(['GET'])
@api.require_api_auth
def detail(request, key):
	from django.shortcuts import get_object_or_404
	proj = get_object_or_404(Project, key=key)
	return JsonResponse(proj._data())
