from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from tracking.models import Notification


@login_required
def notification_feed(request):
	queryset = Notification.objects.filter(recipient=request.user).order_by('-created_at')
	return render(request, 'tracking/notification_feed.html', {'notifications': queryset})


@login_required
def notification_mark_read(request):
	ids = request.POST.getlist('notification_ids') or request.POST.getlist('pk')
	if ids:
		Notification.objects.filter(
			pk__in=ids, recipient=request.user
		).update(read=True)
	return redirect('notification_feed')


@login_required
def notification_list_api(request):
	from tracking.api._common import _page_json
	qs = Notification.objects.filter(recipient=request.user).order_by('-created_at')
	return _page_json(request, qs)
