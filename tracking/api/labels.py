from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from . import _common as api
from tracking.models import Label
from tracking.forms import LabelForm

@api.require_http_methods(['GET', 'POST'])
def collection(request):
	project_key = request.GET.get('project', '')
	if request.method == 'GET':
		if project_key:
			from tracking.models import Project
			project = Project.objects.filter(key=project_key).first()
			qs = project.labels.all() if project else Label.objects.none()
		else:
			qs = Label.objects.none()
		return api._page_json(request, qs)
	elif request.method == 'POST':
		form = LabelForm(request.POST)
		if form.is_valid():
			label = form.save()
			return JsonResponse(label._data(), status=201)
		return JsonResponse(form.errors, status=400)
	return JsonResponse({'error': 'Unsupported method'}, status=405)

@api.require_http_methods(['GET', 'PATCH', 'DELETE'])
def detail(request, pk):
	label = get_object_or_404(Label, pk=pk)
	if request.method == 'GET':
		return JsonResponse(label._data())
	elif request.method == 'PATCH':
		form = LabelForm(request.POST, instance=label)
		if form.is_valid():
			form.save()
			return JsonResponse(label._data())
		return JsonResponse(form.errors, status=400)
	elif request.method == 'DELETE':
		label.delete()
		return JsonResponse({'deleted': pk})
	return JsonResponse({'error': 'Unsupported method'}, status=405)
