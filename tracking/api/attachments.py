from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from . import _common as api
from tracking.models import Attachment, Ticket
from tracking.forms import AttachmentForm

@api.require_http_methods(['GET', 'POST'])
def collection(request):
	ticket_id = request.GET.get('ticket', '')
	if request.method == 'GET':
		if not ticket_id:
			return JsonResponse({'error': 'ticket parameter is required'}, status=400)
		qs = Attachment.objects.filter(ticket=ticket_id)
		return api._page_json(request, qs)
	elif request.method == 'POST':
		if request.FILES:
			ticket_pk = request.POST.get('ticket') or request.GET.get('ticket')
			if not ticket_pk:
				return JsonResponse({'error': 'ticket parameter is required'}, status=400)
			ticket = get_object_or_404(Ticket, pk=ticket_pk)
			form = AttachmentForm(request.POST, request.FILES)
			if form.is_valid():
				att = form.save(commit=False)
				att.ticket = ticket
				att.save()
				return JsonResponse(att._data(), status=201)
		return JsonResponse({'error': 'File required'}, status=400)
	return JsonResponse({'error': 'Unsupported method'}, status=405)

@api.require_http_methods(['GET', 'DELETE'])
def detail(request, pk):
	attachment = get_object_or_404(Attachment, pk=pk)
	if request.method == 'GET':
		return JsonResponse(attachment._data())
	elif request.method == 'DELETE':
		attachment.delete()
		return JsonResponse({'status': 'deleted'})
	return JsonResponse({'error': 'Unsupported method'}, status=405)
