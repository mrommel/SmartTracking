from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.db.models import Count, Sum, Q
from tracking.forms import AvatarForm
from tracking.models import Ticket, TicketActivity, Comment, WorkLog, UserProfile

User = get_user_model()


def _avatar_url(username, size=40):
	"""Generate a deterministic avatar URL using UI Avatars service."""
	return f"https://ui-avatars.com/api/?name={username}&size={size}&background=0D6EFD&color=fff&bold=true"


@login_required
def user_profile(request, pk):
	user = get_object_or_404(User, pk=pk)
	is_owner = request.user.pk == user.pk

	# Stats
	assigned_tickets_count = user.assigned_tickets.count()
	reported_tickets_count = user.reported_tickets.count()
	total_work_logged = WorkLog.objects.filter(author=user).aggregate(Sum("time_spent"))["time_spent__sum"] or 0
	comments_count = user.comments.count()

	# Assigned tickets with state breakdown
	assigned_tickets = (
		user.assigned_tickets.all()
		.select_related('project', 'reporter', 'sprint')
		.prefetch_related('labels', 'components')
		.order_by('-updated_at')
	)
	assigned_by_state = {}
	for state in Ticket.State:
		count = assigned_tickets.filter(state=state).count()
		if count:
			assigned_by_state[state.value] = (state.label, count)

	# Reported tickets
	reported_tickets = (
		user.reported_tickets.all()
		.select_related('project', 'assignee', 'sprint')
		.prefetch_related('labels', 'components')
		.order_by('-created_at')
	)
	reported_by_state = {}
	for state in Ticket.State:
		count = reported_tickets.filter(state=state).count()
		if count:
			reported_by_state[state.value] = (state.label, count)

	# Activity feed: merge TicketActivity + Comments by this user
	activities = (
		TicketActivity.objects.filter(actor=user)
		.select_related('ticket__project')
		.prefetch_related('actor__profile')
		.order_by('-created_at')[:20]
	)
	comments = (
		user.comments
		.select_related('ticket__project')
		.prefetch_related('author__profile')
		.order_by('-created_at')[:20]
	)

	activity_items = []
	for act in activities:
		activity_items.append({
			'type': 'activity',
			'actor': act.actor,
			'action': act.get_action_display(),
			'ticket': act.ticket,
			'created_at': act.created_at,
			'field_name': act.field_name,
			'old_value': act.old_value,
			'new_value': act.new_value,
		})
	for comment in comments:
		activity_items.append({
			'type': 'comment',
			'actor': comment.author,
			'comment_body': comment.body[:200],
			'ticket': comment.ticket,
			'created_at': comment.created_at,
		})
	activity_items.sort(key=lambda x: x['created_at'], reverse=True)
	activity_items = activity_items[:20]

	# Pagination for assigned tickets
	paginator_assigned = Paginator(assigned_tickets, 20)
	page_num_assigned = request.GET.get('assigned_page', 1)
	try:
		page_assigned = paginator_assigned.get_page(page_num_assigned)
	except Exception:
		page_assigned = paginator_assigned.get_page(1)

	# Pagination for reported tickets
	paginator_reported = Paginator(reported_tickets, 20)
	page_num_reported = request.GET.get('reported_page', 1)
	try:
		page_reported = paginator_reported.get_page(page_num_reported)
	except Exception:
		page_reported = paginator_reported.get_page(1)

	context = {
		'user': user,
		'is_owner': is_owner,
		'avatar_form': AvatarForm(),
		'assigned_tickets_count': assigned_tickets_count,
		'reported_tickets_count': reported_tickets_count,
		'total_work_logged': total_work_logged,
		'comments_count': comments_count,
		'assigned_by_state': assigned_by_state,
		'reported_by_state': reported_by_state,
		'activity_items': activity_items,
		'page_assigned': page_assigned,
		'page_reported': page_reported,
		'title': _('Profile') + f' - {user.get_username}',
	}

	return render(request, 'tracking/user_profile.html', context)


@login_required
def user_avatar_update(request, pk):
	"""Upload / replace the profile avatar (owner only, POST)."""
	user = get_object_or_404(User, pk=pk)
	if request.user.pk != user.pk:
		return HttpResponseForbidden()
	if request.method == "POST":
		form = AvatarForm(request.POST, request.FILES)
		if form.is_valid():
			profile, _created = UserProfile.objects.get_or_create(user=user)
			if profile.avatar:
				profile.avatar.delete(save=False)
			profile.avatar = form.cleaned_data["avatar"]
			profile.save()
			messages.success(request, _("Avatar updated"))
			return redirect("user_profile", pk=pk)
		for error in form.errors.get("avatar", []):
			messages.error(request, error)
	return redirect("user_profile", pk=pk)


@login_required
def user_avatar_delete(request, pk):
	"""Remove the profile avatar (owner only, POST)."""
	user = get_object_or_404(User, pk=pk)
	if request.user.pk != user.pk:
		return HttpResponseForbidden()
	if request.method == "POST":
		try:
			profile = user.profile
		except UserProfile.DoesNotExist:
			profile = None
		if profile and profile.avatar:
			profile.avatar.delete()
			messages.success(request, _("Avatar removed"))
	return redirect("user_profile", pk=pk)
