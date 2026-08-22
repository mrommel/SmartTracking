from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from . import _common as api
from tracking.models import Notification

@api.require_http_methods(['GET'])
@api.require_api_auth
def collection(request):
	return api._page_json(request, Notification.objects.filter(recipient=request.user))

@api.require_http_methods(['POST'])
@api.require_api_auth
def mark_read(request, pk):
	notif = get_object_or_404(Notification, pk=pk, recipient=request.user)
	notif.read = True
	notif.save(update_fields=['read'])
	return JsonResponse({'status': 'read'})

@api.require_http_methods(['POST'])
@api.require_api_auth
def mark_all_read(request):
	Notification.objects.filter(recipient=request.user).update(read=True)
	return JsonResponse({'status': 'all_marked_read'})

@api.require_http_methods(['DELETE'])
@api.require_api_auth
def delete_notification(request, pk):
	notif = get_object_or_404(Notification, pk=pk, recipient=request.user)
	notif.delete()
	return JsonResponse({'deleted': pk})
