from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from tracking.models import Watcher, Ticket
from django.contrib.auth import get_user_model
User = get_user_model()

@login_required
def watcher_manage(request, pk):
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == 'POST':
		user_id = request.POST.get('user_id') or request.POST.get('user')
		if user_id:
			user = User.objects.filter(pk=user_id).first()
			if user:
				watcher, created = Watcher.objects.get_or_create(ticket=ticket, user=user)
				if not created:
					messages.info(request, "Already watching")
					return render(request, 'tracking/watcher_manage.html', {'ticket': ticket, 'watchers': ticket.watchers.all(), 'users': User.objects.all()})
		return redirect('ticket_detail', pk=pk)
	watchers = ticket.watchers.all()
	users = User.objects.all()
	return render(request, 'tracking/watcher_manage.html', {'ticket': ticket, 'watchers': watchers, 'users': users})

@login_required
def watcher_remove(request, ticket_pk, user_pk):
	ticket = get_object_or_404(Ticket, pk=ticket_pk)
	watcher = get_object_or_404(Watcher, ticket=ticket, user_id=user_pk)
	watcher.delete()
	return redirect('ticket_detail', pk=ticket_pk)
