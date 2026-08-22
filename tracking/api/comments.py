from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from . import _common as api
from tracking.models import Comment
from tracking.forms import CommentForm

@api.require_http_methods(['GET', 'POST'])
@api.require_api_auth
def collection(request):
	ticket_id = request.GET.get('ticket', '')
	if request.method == 'GET':
		if ticket_id:
			qs = Comment.objects.filter(ticket=ticket_id).order_by('created_at')
		else:
			qs = Comment.objects.none()
		return api._page_json(request, qs)
	elif request.method == 'POST':
		form = CommentForm(request.POST)
		if form.is_valid():
			comment = form.save()
			return JsonResponse(comment._data(), status=201)
		return JsonResponse(form.errors, status=400)
	return JsonResponse({'error': 'Unsupported method'}, status=405)

@api.require_http_methods(['GET', 'DELETE'])
@api.require_api_auth
def detail(request, pk):
	comment = get_object_or_404(Comment, pk=pk)
	if request.method == 'GET':
		return JsonResponse(comment._data())
	elif request.method == 'DELETE':
		comment.delete()
		return JsonResponse({'deleted': pk})
	return JsonResponse({'error': 'Unsupported method'}, status=405)
