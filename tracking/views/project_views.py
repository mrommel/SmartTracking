from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.cache import cache_page
from tracking.models import Project, Ticket
from tracking.forms import ProjectForm
from django.db.models import Count, Q

# Default WIP limits per state for the active-sprint board
_DEFAULT_WIP_LIMITS = {
	'open': 5,
	'in_progress': 8,
	'resolved': 4,
	'closed': 0,
}

def _build_board_context(project, request):
	"""Build the Kanban/swimlane board context for the active-sprint tab."""
	from django.utils import timezone
	board_view = request.GET.get('board_view', 'kanban')
	swimlane_mode = request.GET.get('swimlane', '')

	active_sprint = project.sprints.filter(is_active=True).first()

	# WIP limits: defaults overridable via ?wip__<state>=<n>
	wip_limits = dict(_DEFAULT_WIP_LIMITS)
	for param, val in request.GET.items():
		if param.startswith('wip__'):
			state_name = param[5:]
			try:
				limit = int(val)
				if limit > 0:
					wip_limits[state_name] = limit
			except ValueError:
				pass

	state_ticket_tuples = []
	swimlane_groups = []

	def _wip_flags(state, tickets):
		wip_text = wip_limits.get(state.value, '')
		if wip_text and len(tickets) > wip_text:
			return wip_text, True, True
		return wip_text, wip_text != '', False

	if active_sprint:
		tickets_qs = active_sprint.tickets.select_related('project', 'assignee', 'parent_epic').order_by('-priority', 'created_at')
		tickets = list(tickets_qs)

		state_ticket_map = {}
		for t in tickets:
			state_ticket_map.setdefault(t.state, []).append(t)
		for state in Ticket.State:
			state_tickets = state_ticket_map.get(state.value, [])
			wip_text, wip_over, wip_exceeded = _wip_flags(state, state_tickets)
			state_ticket_tuples.append({'state': state, 'tickets': state_tickets, 'wip_text': wip_text, 'wip_over': wip_over, 'wip_exceeded': wip_exceeded})

		if swimlane_mode:
			group_map = {}
			for t in tickets:
				if swimlane_mode == 'assignee':
					grp = str(t.assignee) if t.assignee else '(Unassigned)'
				elif swimlane_mode == 'epic':
					grp = t.parent_epic.title[:50] if t.parent_epic else '(No Epic)'
				elif swimlane_mode == 'priority':
					grp = t.get_priority_display()
				else:
					grp = 'All'
				group_map.setdefault(grp, []).append(t)

			for grp_name, grp_tickets in sorted(group_map.items(), key=lambda x: 0 if 'unassigned' in x[0].lower() or 'no epic' in x[0].lower() else 1):
				state_ticket_map_grp = {}
				for t in grp_tickets:
					state_ticket_map_grp.setdefault(t.state, []).append(t)
				lane_tickets = []
				for state in Ticket.State:
					state_tickets = state_ticket_map_grp.get(state.value, [])
					wip_text, wip_over, wip_exceeded = _wip_flags(state, state_tickets)
					lane_tickets.append({'state': state, 'tickets': state_tickets, 'wip_text': wip_text, 'wip_over': wip_over, 'wip_exceeded': wip_exceeded})
				swimlane_groups.append((grp_name, lane_tickets))
	else:
		for state in Ticket.State:
			state_ticket_tuples.append({'state': state, 'tickets': [], 'wip_text': '', 'wip_over': False, 'wip_exceeded': False})

	wip_limit_texts = {item['state'].value: item['wip_text'] for item in state_ticket_tuples}

	return {
		'active_sprint': active_sprint,
		'state_ticket_tuples': state_ticket_tuples,
		'board_view': board_view,
		'swimlane_mode': swimlane_mode,
		'wip_limits': wip_limits,
		'wip_limit_texts': wip_limit_texts,
		'swimlane_groups': swimlane_groups if swimlane_mode else [],
		'today': timezone.localdate(),
	}

@login_required
@cache_page(settings.DASHBOARD_CACHE_TIMEOUT)
def dashboard(request):
	project_key = request.GET.get('project_key')
	tab = request.GET.get('tab', 'overview')

	if project_key:
		from django.db.models import Count
		project = get_object_or_404(Project, key=project_key)
		tickets = project.tickets.all().order_by('-created_at')
		context = {
			'project': project,
			'tickets': tickets,
			'tab': tab,
			'ticket_counts': project.tickets.values('state').annotate(count=Count('pk')),
		}
		return render(request, 'tracking/project_detail.html', context)

	from django.db.models import Count
	projects = Project.objects.annotate(ticket_count=Count('tickets')).order_by('-id')
	return render(request, 'tracking/dashboard.html', {'projects': projects})

def health_check(request):
	from django.http import JsonResponse
	return JsonResponse({'status': 'ok'})

@login_required
def project_list(request):
	queryset = Project.objects.annotate(Count('tickets')).order_by('-id')
	page_num = int(request.GET.get('page', 1))
	paginator = Paginator(queryset, 25)
	try:
		page = paginator.page(page_num)
	except Exception:
		page = paginator.page(1)
	return render(request, 'tracking/project_list.html', {'projects': page})

@login_required
@cache_page(settings.DASHBOARD_CACHE_TIMEOUT)
def project_detail(request, pk):
	project = get_object_or_404(Project, pk=pk)
	tab = request.GET.get('tab', 'overview')

	# Shared context: recent tickets
	tickets = project.tickets.all().select_related('assignee').order_by('-created_at')

	context = {'project': project, 'tickets': tickets, 'tab': tab}

	if tab == 'overview':
		from django.utils import timezone
		from django.db.models import Count, Sum
		from datetime import timedelta

		now = timezone.now()
		week_ago = now - timedelta(days=7)

		# State breakdown for the sidebar
		state_breakdown = []
		for state in Ticket.State:
			count = project.tickets.filter(state=state).count()
			state_breakdown.append((state.value, state.label, count))

		# Recent tickets for the sidebar
		recent_tickets = project.tickets.all().select_related('assignee').order_by('-created_at')[:10]

		# Chart data
		state_chart_data = []
		for state in Ticket.State:
			count = project.tickets.filter(state=state).count()
			state_chart_data.append((state.label, count))

		priority_chart_data = []
		for priority in Ticket.Priority:
			count = project.tickets.filter(priority=priority).count()
			priority_chart_data.append((priority.label, count))

		type_chart_data = []
		for ticket_type in Ticket.Type:
			count = project.tickets.filter(type=ticket_type).count()
			type_chart_data.append((ticket_type.label, count))

		# Epic data
		epics = project.tickets.filter(type=Ticket.Type.EPIC)
		epic_data = []
		for epic in epics:
			child_count = epic.child_tickets.count()
			completed = epic.child_tickets.filter(state=Ticket.State.CLOSED).count()
			completion = round(100 * completed / child_count) if child_count else 0
			epic_data.append({'title': epic.title, 'child_count': child_count, 'completion': completion})

		# Time-based metrics
		closed_last_7 = project.tickets.filter(state=Ticket.State.CLOSED, updated_at__gte=week_ago).count()
		updated_last_7 = project.tickets.filter(updated_at__gte=week_ago).count()
		created_last_7 = project.tickets.filter(created_at__gte=week_ago).count()
		due_next_7 = project.tickets.filter(
			due_date__gte=now.date(),
			due_date__lte=now.date() + timedelta(days=7)
		).exclude(state=Ticket.State.CLOSED).count()

		context.update({
			'state_breakdown': state_breakdown,
			'recent_tickets': recent_tickets,
			'state_chart_data': state_chart_data,
			'priority_chart_data': priority_chart_data,
			'type_chart_data': type_chart_data,
			'epic_data': epic_data,
			'closed_last_7': closed_last_7,
			'updated_last_7': updated_last_7,
			'created_last_7': created_last_7,
			'due_next_7': due_next_7,
		})

	elif tab == 'backlog':
 		# Tickets without a sprint (backlog)
 		tickets_without_sprint = project.tickets.filter(sprint__isnull=True).select_related('assignee').order_by('backlog_order', '-created_at')

 		# Filter: show_closed toggle
 		show_closed = request.GET.get('show_closed') != '1'

 		# Sprint ticket lists (all non-backlog sprints with their tickets) — paginated
 		sprint_qs = project.sprints.exclude(pk=1).order_by('order')
 		page_num_sprint = int(request.GET.get('sprint_page', 1))
 		paginator_sprint = Paginator(sprint_qs, 10)
 		try:
 			sprint_page = paginator_sprint.page(page_num_sprint)
 		except Exception:
 			sprint_page = paginator_sprint.page(1)
 		sprint_ticket_list = []
 		for sprint in sprint_page:
 			sprint_tickets = project.tickets.filter(sprint=sprint).select_related('assignee').order_by('-created_at')
 			sprint_ticket_list.append((sprint, sprint_tickets))

 		context.update({
 			'tickets_without_sprint': tickets_without_sprint,
 			'show_closed': show_closed,
 			'sprint_ticket_list': sprint_ticket_list,
 			'sprint_page': sprint_page,
 			'sprint_paginator': paginator_sprint,
 		})

	elif tab == 'active_sprint':
		board_view = request.GET.get('board_view', 'kanban')
		swimlane_mode = request.GET.get('swimlane', '')

		# Find the active sprint for this project
		active_sprint = project.sprints.filter(is_active=True).first()

		# All sprints with their tickets (for the sidebar) — paginated
		sprint_qs = project.sprints.order_by('-order')
		page_num_sprint = int(request.GET.get('sprint_page', 1))
		paginator_sprint = Paginator(sprint_qs, 10)
		try:
			sprint_page = paginator_sprint.page(page_num_sprint)
		except Exception:
			sprint_page = paginator_sprint.page(1)
		sprint_ticket_lists = []
		sprint_state_counts = []
		for sprint in sprint_page:
			sprint_tickets = project.tickets.filter(sprint=sprint).select_related('assignee').order_by('-created_at')
			sprint_ticket_lists.append((sprint, sprint_tickets))

			# State counts for this sprint
			for state in Ticket.State:
				count = sprint_tickets.filter(state=state).count()
				if count:
					sprint_state_counts.append((state.label, count))

		context.update({
			'active_sprint': active_sprint,
			'sprint_ticket_lists': sprint_ticket_lists,
			'sprint_state_counts': sprint_state_counts,
			'sprint_page': sprint_page,
			'sprint_paginator': paginator_sprint,
			'board_view': board_view,
			'swimlane_mode': swimlane_mode,
		})
		context.update(_build_board_context(project, request))

	elif tab == 'reports':
		# State counts
		state_counts = {}
		for state in Ticket.State:
			state_counts[state.value] = project.tickets.filter(state=state).count()

		# Overdue tickets
		from datetime import date
		today = date.today()
		overdue_count = project.tickets.filter(due_date__lt=today).exclude(
			state=Ticket.State.CLOSED
		).count()

		# Assignee workload
		assignee_counts = {}
		for ticket in project.tickets.select_related('assignee'):
			if ticket.assignee:
				name = str(ticket.assignee)
				assignee_counts[name] = assignee_counts.get(name, 0) + 1

		# Versions
		try:
			from tracking.models import Version
			versions = project.versions.all().annotate(ticket_count=Count('tickets')).order_by('-created_at')
		except Exception:
			versions = []

		context.update({
			'state_counts': state_counts,
			'overdue_count': overdue_count,
			'assignee_counts': assignee_counts,
			'versions': versions,
		})

	elif tab == 'velocity':
		# Get completed sprints
		closed_sprints = project.sprints.exclude(is_active=True).order_by('-closed_at')
		has_velocity_data = closed_sprints.exists()

		context.update({
			'sprints': closed_sprints,
		})

	elif tab == 'components':
		context.update({
			'components': project.components.all(),
		})

	elif tab == 'releases':
		try:
			from tracking.models import Version
			versions = project.versions.all().annotate(ticket_count=Count('tickets')).order_by('-created_at')
		except Exception:
			versions = []
		context.update({
			'versions': versions,
		})

	return render(request, 'tracking/project_detail.html', context)

@login_required
def project_edit(request, pk):
	project = get_object_or_404(Project, pk=pk)
	if request.method == 'POST':
		form = ProjectForm(request.POST, instance=project)
		if form.is_valid():
			form.save()
			return redirect('project_detail', pk=pk)
	else:
		form = ProjectForm(instance=project)
	return render(request, 'tracking/project_edit.html', {'form': form, 'project': project})

@login_required
@login_required
def project_create(request):
	if request.method == 'POST':
		form = ProjectForm(request.POST)
		if form.is_valid():
			project = form.save()
			messages.success(request, "Project created")
			return redirect('project_detail', pk=project.pk)
	else:
		form = ProjectForm()
	return render(request, 'tracking/project_form.html', {'form': form, 'title': 'Create project'})

