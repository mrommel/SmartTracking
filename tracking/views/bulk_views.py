from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import redirect, get_object_or_404
from tracking.models import Ticket, Sprint


@login_required
def ticket_bulk_action(request):
	if request.method != 'POST':
		messages.warning(request, 'No action specified')
		return redirect('ticket_list')
	ticket_ids = request.POST.get('ticket_ids', '').strip()
	if ticket_ids:
		ticket_ids = [tid.strip() for tid in ticket_ids.split(',') if tid.strip()]
	else:
		ticket_ids = request.POST.getlist('ticket_ids')
		ticket_ids = [tid for tid in ticket_ids if tid.strip()]
	action = request.POST.get('action', '').strip()
	if not action:
		messages.warning(request, 'No action')
		return redirect('ticket_list')
	if not ticket_ids:
		messages.warning(request, 'No tickets selected')
		return redirect('ticket_list')

	tickets = list(Ticket.objects.filter(pk__in=ticket_ids))
	if not tickets:
		messages.warning(request, 'Some selected tickets do not exist')
		return redirect('ticket_list')

	if action == 'transition':
		new_state = request.POST.get('new_state') or request.POST.get('state', '').strip()
		if not new_state:
			messages.warning(request, 'No state specified')
			return redirect('ticket_list')
		for t in tickets:
			if not t.can_transition_to(new_state):
				messages.warning(
					request,
					f'One or more tickets cannot be moved to {new_state} due to state rules',
				)
				return redirect('ticket_list')
		changed = []
		for t in tickets:
			t.state = new_state
			t.save(update_fields=['state', 'updated_at'])
			changed.append(t)
		messages.success(request, f'{len(changed)} ticket(s) moved to {new_state}')

	elif action == 'delete':
		count = len(tickets)
		Ticket.objects.filter(pk__in=[t.pk for t in tickets]).delete()
		messages.success(request, f'{count} ticket(s) deleted')

	elif action == 'reassign':
		assignee_id = request.POST.get('assignee')
		if assignee_id:
			from django.contrib.auth.models import User
			assignee = get_object_or_404(User, pk=assignee_id)
			Ticket.objects.filter(pk__in=[t.pk for t in tickets]).update(assignee=assignee)
			messages.success(request, f'Reassigned {len(tickets)} ticket(s)')
		else:
			messages.warning(request, 'No assignee selected')
			return redirect('ticket_list')

	elif action == 'labels':
		label_ids = request.POST.getlist('labels')
		if label_ids:
			from tracking.models import Label
			labels = list(Label.objects.filter(pk__in=label_ids))
			for t in tickets:
				t.labels.set(labels)
			messages.success(request, f'Labels updated for {len(tickets)} ticket(s)')
		else:
			messages.warning(request, 'No labels selected')
			return redirect('ticket_list')

	elif action == 'components':
		component_ids = request.POST.getlist('components')
		if component_ids:
			from tracking.models import Component
			components = list(Component.objects.filter(pk__in=component_ids))
			for t in tickets:
				t.components.set(components)
			messages.success(request, f'Components updated for {len(tickets)} ticket(s)')
		else:
			messages.warning(request, 'No components selected')
			return redirect('ticket_list')

	elif action == 'sprint':
		sprint_id = request.POST.get('sprint')
		if sprint_id:
			sprint = get_object_or_404(Sprint, pk=sprint_id)
			Ticket.objects.filter(pk__in=[t.pk for t in tickets]).update(sprint=sprint)
			messages.success(request, f'Moved {len(tickets)} ticket(s) to sprint')
		else:
			messages.warning(request, 'No sprint selected')
			return redirect('ticket_list')

	else:
		messages.warning(request, f'Unknown action: {action}')
		return redirect('ticket_list')

	return redirect('ticket_list')
