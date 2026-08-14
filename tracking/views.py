from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.http.response import HttpResponseBase
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator

from mistune import markdown as render_markdown

from .forms import (
	AttachmentForm, CommentForm, ComponentDeleteForm, ComponentForm,
	LabelDeleteForm, LabelForm, ProjectForm, SprintCloseForm, SprintForm,
	TicketForm, TicketTransitionForm,
)
from .models import Attachment, Comment, Component, Label, Project, Sprint, Ticket, TicketActivity, TicketRelation, Version


def _dashboard_tab_context(project: Project, tickets: models.QuerySet[Ticket], request: HttpRequest, tab: str) -> dict[str, Any]:
	"""Shared context for dashboard tabs filtered by project."""
	today = timezone.localdate()
	seven_days_ago = today - timedelta(days=7)
	seven_days_later = today + timedelta(days=7)

	closed_last_7 = tickets.filter(
		state=Ticket.State.CLOSED,
		updated_at__date__gte=seven_days_ago,
		updated_at__date__lte=today,
	).count()
	updated_last_7 = tickets.filter(
		updated_at__date__gte=seven_days_ago,
		updated_at__date__lte=today,
	).count()
	created_last_7 = tickets.filter(
		created_at__date__gte=seven_days_ago,
		created_at__date__lte=today,
	).count()
	due_next_7 = tickets.filter(
		due_date__isnull=False,
		due_date__gte=today,
		due_date__lte=seven_days_later,
	).count()

	state_counts = {}
	for row in tickets.values("state").annotate(count=Count("id")):
		state_counts[row["state"]] = row["count"]

	priority_counts = {}
	for row in tickets.values("priority").annotate(count=Count("id")):
		priority_counts[row["priority"]] = row["count"]

	type_counts = {}
	for row in tickets.values("type").annotate(count=Count("id")):
		type_counts[row["type"]] = row["count"]

	state_chart_data = [(state.label, state_counts.get(state.value, 0)) for state in Ticket.State]
	priority_chart_data = [
		("Low", priority_counts.get(Ticket.Priority.LOW.value, 0)),
		("Medium", priority_counts.get(Ticket.Priority.MEDIUM.value, 0)),
		("High", priority_counts.get(Ticket.Priority.HIGH.value, 0)),
		("Critical", priority_counts.get(Ticket.Priority.CRITICAL.value, 0)),
	]
	type_chart_data = [
		("Task", type_counts.get(Ticket.Type.TASK.value, 0)),
		("Bug", type_counts.get(Ticket.Type.BUG.value, 0)),
		("Story", type_counts.get(Ticket.Type.STORY.value, 0)),
		("Epic", type_counts.get(Ticket.Type.EPIC.value, 0)),
		("Sub-task", type_counts.get(Ticket.Type.SUBTASK.value, 0)),
	]

	open_states = [Ticket.State.OPEN, Ticket.State.IN_PROGRESS]
	open_tickets = sum(state_counts.get(s, 0) for s in open_states)

	state_breakdown = [
		(state.value, state.label, state_counts.get(state.value, 0))
		for state in Ticket.State
	]

	recent_tickets = (
		tickets.select_related("project", "assignee").order_by("-created_at")[:8]
	)

	my_tickets = tickets.filter(assignee=request.user).count()
	unassigned = tickets.filter(assignee__isnull=True).count()
	overdue = tickets.filter(
		due_date__isnull=False,
		due_date__lt=today,
		state__in=[Ticket.State.OPEN, Ticket.State.IN_PROGRESS],
	).count()

	epics = Ticket.objects.filter(
		type=Ticket.Type.EPIC,
		project=project,
	).select_related("project")
	epic_data = []
	for epic in epics:
		child_count = Ticket.objects.filter(parent_epic=epic).count()
		epic_data.append({
			"id": epic.pk,
			"title": epic.title,
			"child_count": child_count,
			"state": epic.state,
			"completion": epic.child_completion,
		})

	project_sprints = list(Sprint.objects.filter(project=project).select_related("project"))
	sprint_ticket_list = []
	# Order sprints by `order`, but the Backlog pseudo-sprint (name="Backlog", pk=1) must come last.
	non_backlog_sprints = [s for s in project_sprints if not s.is_backlog]
	if non_backlog_sprints:
		max_order_for_non_backlog = max(s.order for s in non_backlog_sprints)
	else:
		max_order_for_non_backlog = 0
	project_sprints.sort(key=lambda s: (1 if s.is_backlog else 0, s.order if not s.is_backlog else max_order_for_non_backlog + 1))
	# Build the sprint-ticket list.  Tickets with `sprint is None` are filtered out
	# here so they appear only in the "tickets_without_sprint" section.
	for sprint in project_sprints:
		if sprint.is_backlog:
			continue
		sprint_ticket_list.append((
			sprint,
			Ticket.objects.select_related("project", "assignee")
			.filter(sprint=sprint)
			.order_by("state", "priority")
		))

	if tab == "backlog":
		qs = Ticket.objects.select_related("project", "assignee").filter(
			sprint__isnull=True, project=project,
		)
		if request.GET.get("show_closed") != "1":
			qs = qs.exclude(state=Ticket.State.CLOSED)
		tickets_without_sprint = qs.order_by("backlog_order", "state", "priority")
		return {
			"tab": tab,
			"tickets_without_sprint": tickets_without_sprint,
			"sprint_ticket_list": sprint_ticket_list,
			"show_closed": request.GET.get("show_closed") == "1",
		}

	if tab == "active_sprint":
		active_sprint = Sprint.objects.filter(project=project, is_active=True).first()
		state_ticket_tuples = []
		swimlane_groups = []
		sprint_ticket_lists = []

		# WIP limits per state (defaults)
		default_wip = {
			"open": 5,
			"in_progress": 8,
			"resolved": 4,
			"closed": 0,
		}
		wip_limits = {}
		for param, val in request.GET.items():
			if param.startswith("wip__"):
				state_name = param[5:]
				try:
					limit = int(val)
					if limit > 0:
						wip_limits[state_name] = limit
				except ValueError:
					pass
		for key, val in default_wip.items():
			if key not in wip_limits:
				wip_limits[key] = val

		if active_sprint:
			tickets_qs = active_sprint.tickets.select_related("project", "assignee", "parent_epic").order_by("backlog_order", "-priority", "created_at")

			state_ticket_map = {}
			for t in tickets_qs:
				state_ticket_map.setdefault(t.state, []).append(t)
			for state in Ticket.State:
				if state.value in state_ticket_map:
					tickets = state_ticket_map[state.value]
					wip_text = wip_limits.get(state.value, "")
					if wip_text and int(wip_text) and len(tickets) > int(wip_text):
						wip_over = True
						wip_exceeded = True
					else:
						wip_over = wip_text != ""
						wip_exceeded = False
					state_ticket_tuples.append({"state": state, "tickets": tickets, "wip_text": wip_text, "wip_over": wip_over, "wip_exceeded": wip_exceeded})
				else:
					state_ticket_tuples.append({"state": state, "tickets": [], "wip_text": "", "wip_over": False, "wip_exceeded": False})

			# Build swimlane groups if requested
			swimlane_mode = request.GET.get("swimlane", "")
			if swimlane_mode:
				group_map = {}
				for t in tickets_qs:
					if swimlane_mode == "assignee" and t.assignee:
						grp = str(t.assignee)
					elif swimlane_mode == "assignee":
						grp = "(Unassigned)"
					elif swimlane_mode == "epic" and t.parent_epic:
						grp = t.parent_epic.title[:50]
					elif swimlane_mode == "epic":
						grp = "(No Epic)"
					elif swimlane_mode == "priority":
						grp = t.get_priority_display()
					else:
						grp = "All"
					group_map.setdefault(grp, []).append(t)

				for grp_name, grp_tickets in sorted(group_map.items(), key=lambda x: 0 if "unassigned" in x[0].lower() or "no epic" in x[0].lower() else 1):
					state_ticket_map_grp = {}
					for t in grp_tickets:
						state_ticket_map_grp.setdefault(t.state, []).append(t)
					lane_tickets = []
					for state in Ticket.State:
						tickets = state_ticket_map_grp.get(state.value, [])
						wip_text = wip_limits.get(state.value, "")
						if wip_text and int(wip_text) and len(tickets) > int(wip_text):
							wip_over = True
							wip_exceeded = True
						else:
							wip_over = wip_text != ""
							wip_exceeded = False
						lane_tickets.append({"state": state, "tickets": tickets, "wip_text": wip_text, "wip_over": wip_over, "wip_exceeded": wip_exceeded})
					swimlane_groups.append((grp_name, lane_tickets))

		else:
			for state in Ticket.State:
				state_ticket_tuples.append({"state": state, "tickets": [], "wip_text": "", "wip_over": False, "wip_exceeded": False})

		# Build other sprints' ticket lists for the sprint section
		other_sprints = Sprint.objects.filter(
			project=project, is_active=False
		).exclude(pk=1).order_by("-end_date", "-created_at")
		for sp in other_sprints:
			sprint_ticket_lists.append((
				sp,
				Ticket.objects.select_related("project", "assignee").filter(sprint=sp).order_by("-priority"),
			))

		# Swimlane configuration from query param
		if "swimlane_mode" not in locals():
			swimlane_mode = ""
		board_view = request.GET.get("board_view", "kanban")
		if not swimlane_mode and board_view == "swimlane":
			swimlane_mode = ""

		wip_limit_texts = {}
		for item in state_ticket_tuples:
			state_key = item["state"].value if hasattr(item["state"], "value") else "open"
			wip_limit_texts[state_key] = item.get("wip_text", wip_limits.get(state_key, ""))

		return {
			"tab": tab,
			"active_sprint": active_sprint,
			"state_ticket_tuples": state_ticket_tuples,
			"board_view": board_view,
			"swimlane_mode": swimlane_mode,
			"wip_limits": wip_limits,
			"wip_limit_texts": wip_limit_texts,
			"swimlane_groups": swimlane_groups if swimlane_mode else [],
			"sprint_ticket_lists": sprint_ticket_lists,
			"project": project,
			"today": today,
		}

	return {
		"tab": tab,
		"open_tickets": open_tickets,
		"project_count": Project.objects.count(),
		"critical_count": priority_counts.get(Ticket.Priority.CRITICAL.value, 0),
		"state_breakdown": state_breakdown,
		"recent_tickets": recent_tickets,
		"my_tickets": my_tickets,
		"unassigned": unassigned,
		"overdue_count": overdue,
		"closed_last_7": closed_last_7,
		"updated_last_7": updated_last_7,
		"created_last_7": created_last_7,
		"due_next_7": due_next_7,
		"state_chart_data": state_chart_data,
		"priority_chart_data": priority_chart_data,
		"type_chart_data": type_chart_data,
		"epic_data": epic_data,
		"sprint_ticket_list": sprint_ticket_list,
		"active_sprint": Sprint.objects.filter(project=project, is_active=True).first(),
	}


@login_required
def dashboard(request: HttpRequest) -> HttpResponseBase:
	"""Landing page: lists projects, then tab navigation per selected project."""
	projects = Project.objects.annotate(ticket_count=Count("tickets")).order_by("key")
	project_key = request.GET.get("project_key")
	selected_project = None
	if project_key:
		proj = get_object_or_404(Project, key=project_key)
		selected_project = proj

	tab = request.GET.get("tab", "overview")
	valid_tabs = ["overview", "backlog", "active_sprint"]
	if tab not in valid_tabs:
		tab = "overview"

	if selected_project:
		tickets = Ticket.objects.filter(project=selected_project)
		total_tickets = tickets.count()
		tab_context = _dashboard_tab_context(selected_project, tickets, request, tab)
	else:
		total_tickets = 0
		tab_context = {}

	return render(request, "tracking/dashboard.html", {
		"title": "Dashboard",
		"projects": projects,
		"selected_project": selected_project,
		"tab": tab,
		"total_tickets": total_tickets,
		**tab_context,
	})


@login_required
def reports(request: HttpRequest) -> HttpResponseBase:
	"""Reports page with project-level analytics."""
	projects = Project.objects.annotate(ticket_count=Count("tickets")).order_by("key")
	project_key = request.GET.get("project")
	selected_project = None
	today = timezone.localdate()

	state_counts = {"open": 0, "in_progress": 0, "resolved": 0, "closed": 0}
	component_counts = {}
	assignee_counts = {}
	overdue_count = 0

	if project_key:
		selected_project = get_object_or_404(Project, key=project_key)
		tickets = Ticket.objects.filter(project=selected_project)
		for row in tickets.values("state").annotate(count=Count("id")):
			state_counts[row["state"]] = row["count"]
		for row in tickets.values("components__name").annotate(count=Count("id")).order_by("-count"):
			component_counts[row["components__name"]] = row["count"]
		for row in tickets.values("assignee__username").annotate(count=Count("id")).order_by("-count"):
			assignee_counts[row["assignee__username"]] = row["count"]
		overdue_count = tickets.filter(
			due_date__isnull=False,
			due_date__lt=today,
			state__in=[Ticket.State.OPEN, Ticket.State.IN_PROGRESS],
		).count()

	return render(request, "tracking/reports.html", {
		"title": "Reports",
		"tab": "reports",
		"projects": projects,
		"selected_project": selected_project,
		"state_counts": state_counts,
		"component_counts": component_counts,
		"assignee_counts": assignee_counts,
		"overdue_count": overdue_count,
		"today": today,
	})


@login_required
def releases(request: HttpRequest) -> HttpResponseBase:
	"""Versions / releases page with CRUD."""
	projects = Project.objects.annotate(ticket_count=Count("tickets")).order_by("key")
	project_key = request.GET.get("project")
	selected_project = None
	versions = Version.objects.none()
	version_form = None

	if project_key:
		selected_project = get_object_or_404(Project, key=project_key)
		versions = selected_project.versions.annotate(
			ticket_count=Count("affected_tickets")
		).order_by("-release_date", "-target_date", "-created_at")
		if request.method == "POST":
			from .forms import VersionForm
			version_form = VersionForm(request.POST, project=selected_project, data=request.POST)
			if version_form.is_valid():
				version = version_form.save(commit=False)
				version.project = selected_project
				version.save()
				messages.success(request, f"Version '{version.name}' created.")
				return redirect("releases", project=project_key)
		else:
			version_form = VersionForm(project=selected_project)

	return render(request, "tracking/releases.html", {
		"title": "Releases",
		"tab": "releases",
		"projects": projects,
		"selected_project": selected_project,
		"versions": versions,
		"version_form": version_form,
	})


@login_required
def project_list(request: HttpRequest) -> HttpResponseBase:
	"""Show all projects with their ticket counts."""
	projects = Project.objects.annotate(ticket_count=Count("tickets")).order_by("key")
	return render(request, "tracking/project_list.html", {
		"title": "Projects",
		"projects": projects,
	})


@login_required
def project_detail(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Show a project with its tabbed views (Overview, Backlog, Active Sprint, Reports, Components, Releases)."""
	tab = request.GET.get("tab", "overview")
	valid_tabs = ["overview", "backlog", "active_sprint", "reports", "components", "releases"]
	if tab not in valid_tabs:
		tab = "overview"

	project = get_object_or_404(
		Project.objects.annotate(ticket_count=Count("tickets")), pk=pk
	)
	tickets = Ticket.objects.select_related("project", "assignee").filter(project=project)
	components = project.components.all()
	labels = project.labels.all()

	context = {
		"title": project.key,
		"project": project,
		"tab": tab,
		"components": components,
		"labels": labels,
	}

	if tab == "overview":
		ctx = _dashboard_tab_context(project, tickets, request, "overview")
		context.update({k: v for k, v in ctx.items() if k != "tab"})
		context["selected_project"] = project

	if tab == "backlog":
		ctx = _dashboard_tab_context(project, tickets, request, "backlog")
		context.update({k: v for k, v in ctx.items() if k != "tab"})
		context["selected_project"] = project

	if tab == "active_sprint":
		ctx = _dashboard_tab_context(project, tickets, request, "active_sprint")
		context.update({k: v for k, v in ctx.items() if k != "tab"})
		context["selected_project"] = project
		context["sprints"] = Sprint.objects.filter(project=project).select_related("project").order_by("order")

	if tab == "components":
		context["components"] = components

	if tab == "reports":
		today = timezone.localdate()
		state_counts = {}
		component_counts = {}
		assignee_counts = {}
		for row in tickets.values("state").annotate(count=Count("id")):
			state_counts[row["state"]] = row["count"]
		for row in tickets.values("components__name").annotate(count=Count("id")).order_by("-count"):
			component_counts[row["components__name"]] = row["count"]
		for row in tickets.values("assignee__username").annotate(count=Count("id")).order_by("-count"):
			assignee_counts[row["assignee__username"]] = row["count"]
		overdue_count = tickets.filter(
			due_date__isnull=False,
			due_date__lt=today,
			state__in=[Ticket.State.OPEN, Ticket.State.IN_PROGRESS],
		).count()
		context.update({
			"state_counts": state_counts,
			"component_counts": component_counts,
			"assignee_counts": assignee_counts,
			"overdue_count": overdue_count,
		})

	if tab == "releases":
		context["versions"] = (
			project.versions.annotate(ticket_count=Count("affected_tickets"))
			.order_by("-release_date", "-target_date", "-created_at")
		)

	return render(request, "tracking/project_detail.html", context)


@login_required
def project_create(request: HttpRequest) -> HttpResponseBase:
	"""Create a new project."""
	if request.method == "POST":
		form = ProjectForm(request.POST)
		if form.is_valid():
			project = form.save()
			messages.success(request, f"Project '{project.key}' created.")
			return redirect("project_list")
	else:
		form = ProjectForm()

	return render(request, "tracking/project_form.html", {
		"title": "New project",
		"form": form,
	})


@login_required
def project_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Edit an existing project (name, description only)."""
	project = get_object_or_404(Project, pk=pk)
	if request.method == "POST":
		form = ProjectForm(request.POST, instance=project)
		if form.is_valid():
			form.save()
			messages.success(request, f"Project '{project.key}' updated.")
			return redirect("project_detail", pk=project.pk)
	else:
		form = ProjectForm(instance=project)

	return render(request, "tracking/project_edit.html", {
		"title": f"Edit {project.key}",
		"form": form,
		"project": project,
	})


@login_required
def ticket_list(request: HttpRequest) -> HttpResponseBase:
	"""List tickets, optionally filtered by project, state, component, and label."""
	tickets = _build_tickets_queryset(request)

	query = request.GET.get("q")
	if query:
		tickets = tickets.filter(
			Q(title__icontains=query) | Q(description__icontains=query)
		)

	project_key = request.GET.get("project")
	if project_key:
		tickets = tickets.filter(project__key=project_key)

	state = request.GET.get("state")
	if state:
		tickets = tickets.filter(state=state)

	component = request.GET.get("component")
	if component:
		tickets = tickets.filter(components__name=component)

	label = request.GET.get("label")
	if label:
		tickets = tickets.filter(labels__name=label)

	assignee = request.GET.get("assignee")
	if assignee == "me":
		tickets = tickets.filter(assignee=request.user)
	elif assignee == "unassigned":
		tickets = tickets.filter(assignee__isnull=True)
	elif assignee:
		tickets = tickets.filter(assignee__pk=assignee)

	tickets = tickets.order_by("-updated_at")
	page = request.GET.get("page", 1)
	paginator = Paginator(tickets, 25)
	ticket_page = paginator.get_page(page)

	# Build JSON lists for bulk action dropdowns
	users_json = json.dumps([["u" + str(u.pk), str(u)] for u in get_user_model().objects.filter(
		id__in=Ticket.objects.values_list("assignee", flat=True).distinct()
	).order_by("username")])
	labels_json = json.dumps([["l" + str(l.pk), l.name + " (" + l.project.key + ")"] for l in Label.objects.all().order_by("name")])
	components_json = json.dumps([["c" + str(c.pk), c.name + " (" + c.project.key + ")"] for c in Component.objects.all().order_by("name")])
	sprints_json = json.dumps([["s" + str(s.pk), s.name + " (" + s.project.key + ")"] for s in Sprint.objects.all().order_by("order")])

	return render(request, "tracking/ticket_list.html", {
		"title": "Tickets",
		"tickets": ticket_page,
		"projects": Project.objects.all(),
		"states": Ticket.State.choices,
		"current_project": project_key or "",
		"current_state": state or "",
		"current_component": component or "",
		"current_label": label or "",
		"current_assignee": assignee or "",
		"current_query": query or "",
		"components": Component.objects.all().order_by("name"),
		"labels": Label.objects.all().order_by("name"),
		"users": get_user_model().objects.filter(
			id__in=Ticket.objects.values_list("assignee", flat=True).distinct()
		).order_by("username"),
		"users_json": users_json,
		"labels_json": labels_json,
		"components_json": components_json,
		"sprints_json": sprints_json,
	})


@login_required
def ticket_detail(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Show a single ticket with its allowed state transitions, comments, and attachments."""
	ticket = get_object_or_404(
		Ticket.objects.select_related("project", "assignee", "reporter", "parent_epic"), pk=pk
	)
	comments = ticket.comments.select_related("author").all()
	attachments = ticket.attachments.all()
	image_attachments = [a for a in attachments if a.is_image]
	child_tickets = Ticket.objects.filter(parent_epic=ticket).select_related("project", "assignee").order_by("backlog_order", "pk")
	relations = list(ticket.relations.prefetch_related("subject", "target").all())
	for rel in relations:
		if rel.subject_id == ticket.pk:
			rel.label = str(rel.get_relation_type_display())
		else:
			rel.label = ticket._get_reverse_label(rel.relation_type)
	activities = ticket.activities.select_related("actor").all()
	page = request.GET.get("comments_page", 1)
	comment_paginator = Paginator(comments, 20)
	comment_page = comment_paginator.get_page(page)
	return render(request, "tracking/ticket_detail.html", {
		"title": ticket.title,
		"ticket": ticket,
		"transition_form": TicketTransitionForm(ticket=ticket),
		"comment_form": CommentForm(),
		"comments": comment_page,
 		"attachments": attachments,
 		"image_attachments": image_attachments,
		"relations": relations,
		"available_tickets": ticket.available_rels_for("current_project"),
		"relation_types": Ticket.RelationType.choices,
		"child_tickets": child_tickets,
		"sprints": Sprint.objects.filter(project=ticket.project).order_by("order"),
		"activities": activities,
	})


@login_required
def ticket_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Edit an existing ticket."""
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == "POST":
		form = TicketForm(request.POST)
		if form.is_valid():
			# Snapshot old values for activity logging
			old_cmp = set(ticket.components.values_list("pk", flat=True))
			old_lbl = set(ticket.labels.values_list("pk", flat=True))
			ticket.title = form.cleaned_data["title"]
			ticket.description = form.cleaned_data["description"]
			ticket.type = form.cleaned_data["type"]
			ticket.estimation = form.cleaned_data["estimation"]
			ticket.priority = form.cleaned_data["priority"]
			ticket.assignee = form.cleaned_data["assignee"]
			ticket.parent_epic = form.cleaned_data["parent_epic"]
			ticket.due_date = form.cleaned_data["due_date"]
			ticket.save(update_fields=["title", "description", "type", "estimation",
				"priority", "assignee", "parent_epic", "due_date", "updated_at"])
			for cmp in set(ticket.components.all()) - old_cmp:
				TicketActivity.objects.create(ticket=ticket, actor=request.user,
					action=TicketActivity.Action.COMPONENT_ADDED,
					field_name="component", new_value=cmp.name)
			for lbl in set(ticket.labels.all()) - old_lbl:
				TicketActivity.objects.create(ticket=ticket, actor=request.user,
					action=TicketActivity.Action.LABEL_ADDED,
					field_name="label", new_value=lbl.name)
			messages.success(request, "Ticket updated.")
			return redirect("ticket_detail", pk=ticket.pk)
	else:
		form = TicketForm(instance=ticket)
		project_key = ticket.project.key
		form.fields["parent_epic"].queryset = Ticket.objects.filter(project=ticket.project, type=Ticket.Type.EPIC).exclude(pk=ticket.pk)
		form.fields["components"].queryset = Component.objects.filter(project=ticket.project)
		form.fields["labels"].queryset = Label.objects.filter(project=ticket.project)

	return render(request, "tracking/ticket_form.html", {
		"title": f"Edit — {ticket.title}",
		"form": form,
		"ticket": ticket,
	})


@login_required
def ticket_create(request: HttpRequest) -> HttpResponseBase:
	"""Create a new ticket."""
	if request.method == "POST":
		form = TicketForm(request.POST)
		if form.is_valid():
			ticket = form.save(commit=False)
			if request.user.is_authenticated:
				ticket.reporter = request.user
			ticket.save()
			TicketActivity.objects.create(ticket=ticket, actor=request.user,
				action=TicketActivity.Action.TICKET_CREATED)
			messages.success(request, "Ticket created.")
			return redirect("ticket_detail", pk=ticket.pk)
	else:
		form = TicketForm()
		# Pre-populate components/labels for the selected project
		project_key = request.GET.get("project")
		if project_key:
			form.fields["components"].queryset = Component.objects.filter(
				project__key=project_key.upper()
			)
			form.fields["labels"].queryset = Label.objects.filter(
				project__key=project_key.upper()
			)

	return render(request, "tracking/ticket_form.html", {
		"title": "New ticket",
		"form": form,
	})


@login_required
def ticket_transition(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Apply a state transition to a ticket if it is allowed."""
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == "POST":
		form = TicketTransitionForm(request.POST, ticket=ticket)
		if form.is_valid():
			old_state = ticket.state
			ticket.state = form.cleaned_data["state"]
			ticket.save(update_fields=["state", "updated_at"])
			TicketActivity.objects.create(ticket=ticket, actor=request.user,
				action=TicketActivity.Action.STATE_CHANGED,
				old_value=old_state, new_value=ticket.state)
			messages.success(request, f"Ticket moved to '{ticket.get_state_display()}'.")
		else:
			messages.error(request, "Invalid state transition.")
	return redirect(reverse("ticket_detail", args=[ticket.pk]))


@login_required
def ticket_sprint_assign(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Assign a ticket to a sprint (only within the same project)."""
	ticket = get_object_or_404(Ticket, pk=pk)
	old_sprint = ticket.sprint_id
	if request.method == "POST":
		sprint_id = request.POST.get("sprint")
		if sprint_id == "":
			ticket.sprint = None
		elif sprint_id:
			sprint_obj = get_object_or_404(Sprint, pk=sprint_id, project=ticket.project)
			ticket.sprint = sprint_obj
		ticket.save(update_fields=["sprint", "updated_at"])
		if old_sprint != ticket.sprint_id:
			new_sprint_name = ticket.sprint.name if ticket.sprint else "(backlog)"
			TicketActivity.objects.create(ticket=ticket, actor=request.user,
				action=TicketActivity.Action.SPRINT_CHANGED,
				old_value=str(old_sprint), new_value= new_sprint_name)
		messages.success(request, f"Ticket assigned to sprint.")
	return redirect(reverse("ticket_detail", args=[ticket.pk]))


@login_required
@require_POST
def update_backlog_order(request: HttpRequest) -> HttpResponseBase:
	"""Update backlog_order for multiple tickets (used after drag-to-reorder)."""
	try:
		data = json.loads(request.body)
		order_map = data.get("order", [])
	except (json.JSONDecodeError, TypeError):
		return HttpResponse(status=400, content='{"error": "Invalid JSON"}')

	if not isinstance(order_map, list):
		return HttpResponse(status=400, content='{"error": "Expected list"}')

	updated = []
	for item in order_map:
		ticket_id = item.get("id")
		order_val = item.get("order")
		if ticket_id and order_val is not None:
			try:
				ticket_id = int(ticket_id)
				order_val = int(order_val)
				ticket = Ticket.objects.get(pk=ticket_id)
				ticket.backlog_order = order_val
				ticket.save(update_fields=["backlog_order", "updated_at"])
				updated.append(ticket_id)
			except (ValueError, Ticket.DoesNotExist):
				pass

	return HttpResponse(
		json.dumps({"updated": updated}),
		content_type="application/json",
	)


@login_required
def sprint_create(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Create a new sprint for a project."""
	project = get_object_or_404(Project, pk=pk)
	if request.method == "POST":
		form = SprintForm(request.POST, project=project)
		if form.is_valid():
			sprint = form.save(commit=False)
			sprint.project = project
			sprint.save()
			messages.success(request, f"Sprint '{sprint.name}' created.")
			return redirect(reverse("project_detail", args=[project.pk]) + "?tab=active_sprint")
	else:
		form = SprintForm(project=project)
	return render(request, "tracking/sprint_form.html", {
		"title": f"New sprint — {project.key}",
		"form": form,
		"project": project,
	})


@login_required
def sprint_edit(request: HttpRequest, project_pk: int, sprint_pk: int) -> HttpResponseBase:
	"""Edit an existing sprint for a project."""
	sprint = get_object_or_404(Sprint, pk=sprint_pk)
	project = sprint.project
	if request.method == "POST":
		form = SprintForm(request.POST, project=project, instance=sprint)
		if form.is_valid():
			sprint = form.save()
			messages.success(request, f"Sprint '{sprint.name}' updated.")
			return redirect(reverse("project_detail", args=[project.pk]) + "?tab=active_sprint")
	else:
		form = SprintForm(project=project, instance=sprint)
	return render(request, "tracking/sprint_form.html", {
		"title": f"Edit sprint — {project.key}",
		"form": form,
		"sprint": sprint,
		"project": project,
	})


@login_required
def sprint_close(request: HttpRequest, project_pk: int, sprint_pk: int) -> HttpResponseBase:
	"""Show close sprint confirmation form, or close the sprint with ticket handling options."""
	sprint = get_object_or_404(Sprint, pk=sprint_pk)
	project = sprint.project
	if request.method == "POST":
		form = SprintCloseForm(request.POST, project=project, exclude_sprint=sprint)
		if form.is_valid():
			action = form.cleaned_data["action"]
			target_sprint_id = None
			if action == "sprint":
				target_sprint_id = form.cleaned_data["target_sprint"].pk
			sprint.close_with_action(action, target_sprint_id)
			messages.success(request, f"Sprint '{sprint.name}' closed.")
			return redirect(reverse("project_detail", args=[project.pk]) + "?tab=active_sprint")
	else:
		form = SprintCloseForm(project=project, exclude_sprint=sprint)
	return render(request, "tracking/sprint_close.html", {
		"title": f"Close sprint — {project.key}",
		"form": form,
		"sprint": sprint,
		"project": project,
	})


@login_required
def ticket_comment_create(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Add a comment to a ticket."""
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == "POST":
		form = CommentForm(request.POST)
		if form.is_valid():
			comment = form.save(commit=False)
			comment.ticket = ticket
			comment.author = request.user
			comment.save()
			TicketActivity.objects.create(ticket=ticket, actor=request.user,
				action=TicketActivity.Action.COMMENT_ADDED)
			messages.success(request, "Comment added.")
			return redirect("ticket_detail", pk=ticket.pk)
		return redirect("ticket_detail", pk=ticket.pk)


@login_required
def ticket_comment_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Edit an existing comment on a ticket."""
	comment = get_object_or_404(Comment, pk=pk)
	ticket = comment.ticket
	if request.method == "POST":
		form = CommentEditForm(request.POST, instance=comment)
		if form.is_valid():
			old_body = comment.body
			new_body = form.cleaned_data["body"]
			comment = form.save()
			if old_body != new_body:
				CommentEditHistory.objects.create(
					comment=comment,
					old_body=old_body,
					new_body=new_body,
					actor=request.user,
				)
				TicketActivity.objects.create(ticket=ticket, actor=request.user,
					action=TicketActivity.Action.COMMENT_ADDED)
			messages.success(request, "Comment updated.")
			return redirect("ticket_detail", pk=ticket.pk)
	else:
		form = CommentEditForm(instance=comment)
	return redirect("ticket_detail", pk=ticket.pk)


@login_required
def ticket_comment_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Delete a comment."""
	comment = get_object_or_404(Comment, pk=pk)
	ticket = comment.ticket
	if request.method == "POST":
		TicketActivity.objects.create(ticket=ticket, actor=request.user,
			action=TicketActivity.Action.COMMENT_DELETED)
		comment.delete()
		messages.success(request, "Comment deleted.")
	return redirect("ticket_detail", pk=ticket.pk)


@login_required
def ticket_relation_add(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Add a relation from the current ticket to another ticket."""
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == "POST":
		target_id = request.POST.get("target_ticket")
		relation_type = request.POST.get("relation_type")
		try:
			target = Ticket.objects.get(pk=target_id)
		except (ValueError, Ticket.DoesNotExist):
			messages.error(request, "Invalid target ticket.")
			return redirect("ticket_detail", pk=ticket.pk)
		if target.project != ticket.project:
			messages.error(request, "Target ticket must be in the same project.")
			return redirect("ticket_detail", pk=ticket.pk)
		if not relation_type:
			messages.error(request, "Please select a relation type.")
			return redirect("ticket_detail", pk=ticket.pk)
		# Check if the relation already exists
		if TicketRelation.objects.filter(
			subject=ticket, target=target, relation_type=relation_type
		).exists():
			messages.info(request, "This relation already exists.")
			return redirect("ticket_detail", pk=ticket.pk)
		# Also check the reverse direction
		if TicketRelation.objects.filter(
			subject=target, target=ticket, relation_type=relation_type
		).exists():
			messages.info(request, "This relation already exists.")
			return redirect("ticket_detail", pk=ticket.pk)
		relation = TicketRelation.objects.create(
			subject=ticket,
			target=target,
			relation_type=relation_type,
		)
		TicketActivity.objects.create(ticket=ticket, actor=request.user,
			action=TicketActivity.Action.RELATION_ADDED,
			new_value=f"{target.pk}: {relation.get_relation_type_display()}")
		messages.success(request, "Relation added.")
		return redirect("ticket_detail", pk=ticket.pk)
	return redirect("ticket_detail", pk=ticket.pk)


@login_required
def ticket_relation_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Delete a relation."""
	relation = get_object_or_404(TicketRelation, pk=pk)
	# Ensure the relation's tickets are in the same project
	if relation.subject.project != relation.target.project:
		messages.error(request, "Cannot delete relation between tickets in different projects.")
		return redirect("ticket_detail", pk=relation.subject.pk)
	ticket = relation.subject
	if request.method == "POST":
		TicketActivity.objects.create(ticket=ticket, actor=request.user,
			action=TicketActivity.Action.RELATION_REMOVED,
			new_value=f"{relation.target.pk}: {relation.get_relation_type_display()}")
		relation.delete()
		# Also delete the symmetric counterpart if it exists
		reverse_map = Ticket._REVERSE_LABELS or {}
		if relation.relation_type in reverse_map:
			try:
				TicketRelation.objects.get(
					subject=relation.target,
					target=relation.subject,
					relation_type=reverse_map[relation.relation_type],
				).delete()
			except TicketRelation.DoesNotExist:
				pass
		messages.success(request, "Relation removed.")
	return redirect("ticket_detail", pk=ticket.pk)


@login_required
def label_list(request: HttpRequest, pk: int | None = None) -> HttpResponseBase:
	"""List and manage labels for a project."""
	if pk is not None:
		project = get_object_or_404(Project, pk=pk)
	else:
		project_key = request.GET.get("project")
		if project_key:
			project = get_object_or_404(Project, key=project_key.upper())
		else:
			# No project specified — show all labels across all projects
			return render(request, "tracking/label_list.html", {
				"title": "Labels",
				"project": None,
				"labels": Label.objects.all().order_by("project__key", "name"),
				"projects": Project.objects.all(),
			})
	return render(request, "tracking/label_list.html", {
		"title": f"Labels — {project.key}",
		"project": project,
		"labels": project.labels.all().order_by("name"),
	})


@login_required
def label_create(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Create a new label for a project."""
	project = get_object_or_404(Project, pk=pk)
	if request.method == "POST":
		form = LabelForm(request.POST, project=project)
		if form.is_valid():
			label = form.save(commit=False)
			label.project = project
			label.save()
			messages.success(request, f"Label '{label.name}' created.")
			return redirect("label_list", pk=project.pk)
	else:
		form = LabelForm(project=project)

	return render(request, "tracking/label_form.html", {
		"title": f"New label — {project.key}",
		"form": form,
		"project": project,
	})


@login_required
def label_update(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Edit an existing label."""
	label = get_object_or_404(Label, pk=pk)
	if request.method == "POST":
		form = LabelForm(request.POST, instance=label, project=label.project)
		if form.is_valid():
			label = form.save()
			messages.success(request, f"Label '{label.name}' updated.")
			return redirect("label_list", pk=label.project.pk)
	else:
		form = LabelForm(instance=label, project=label.project)

	return render(request, "tracking/label_form.html", {
		"title": f"Edit label — {label.project.key}",
		"form": form,
		"project": label.project,
		"label": label,
	})


@login_required
def label_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Delete a label."""
	label = get_object_or_404(Label, pk=pk)
	project = label.project
	if request.method == "POST":
		form = LabelDeleteForm(request.POST, project=project)
		if form.is_valid():
			selected_label = form.cleaned_data["label"]
			name = selected_label.name
			selected_label.delete()
			messages.success(request, f"Label '{name}' deleted.")
			return redirect("label_list", pk=project.pk)
	else:
		form = LabelDeleteForm(project=project)

	return render(request, "tracking/label_delete.html", {
		"title": f"Delete label — {project.key}",
		"form": form,
		"project": project,
		"label": label,
	})


@login_required
def component_list(request: HttpRequest, pk: int | None = None) -> HttpResponseBase:
	"""List and manage components for a project."""
	if pk is not None:
		project = get_object_or_404(Project, pk=pk)
	else:
		project_key = request.GET.get("project")
		if project_key:
			project = get_object_or_404(Project, key=project_key.upper())
		else:
			return render(request, "tracking/component_list.html", {
				"title": "Components",
				"project": None,
				"components": Component.objects.all().order_by("project__key", "name"),
				"projects": Project.objects.all(),
			})
	return render(request, "tracking/component_list.html", {
		"title": f"Components — {project.key}",
		"project": project,
		"components": project.components.all().order_by("name"),
	})


@login_required
def component_create(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Create a new component for a project."""
	project = get_object_or_404(Project, pk=pk)
	if request.method == "POST":
		form = ComponentForm(request.POST, project=project)
		if form.is_valid():
			component = form.save(commit=False)
			component.project = project
			component.save()
			messages.success(request, f"Component '{component.name}' created.")
			return redirect("component_list", pk=project.pk)
	else:
		form = ComponentForm(project=project)

	return render(request, "tracking/component_form.html", {
		"title": f"New component — {project.key}",
		"form": form,
		"project": project,
	})


@login_required
def component_update(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Edit an existing component."""
	component = get_object_or_404(Component, pk=pk)
	if request.method == "POST":
		form = ComponentForm(request.POST, instance=component, project=component.project)
		if form.is_valid():
			component = form.save()
			messages.success(request, f"Component '{component.name}' updated.")
			return redirect("component_list", pk=component.project.pk)
	else:
		form = ComponentForm(instance=component, project=component.project)

	return render(request, "tracking/component_form.html", {
		"title": f"Edit component — {component.project.key}",
		"form": form,
		"project": component.project,
		"component": component,
	})


@login_required
def component_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Delete a component."""
	component = get_object_or_404(Component, pk=pk)
	project = component.project
	if request.method == "POST":
		form = ComponentDeleteForm(request.POST, project=project)
		if form.is_valid():
			selected_component = form.cleaned_data["component"]
			name = selected_component.name
			selected_component.delete()
			messages.success(request, f"Component '{name}' deleted.")
			return redirect("component_list", pk=project.pk)
	else:
		form = ComponentDeleteForm(project=project)

	return render(request, "tracking/component_delete.html", {
		"title": f"Delete component — {project.key}",
		"form": form,
		"project": project,
		"component": component,
	})


@login_required
def ticket_delete(request: HttpRequest, project_pk: int, pk: int) -> HttpResponseBase:
	"""Delete a ticket."""
	ticket = get_object_or_404(Ticket.objects.select_related("project"), pk=pk)
	if ticket.project.pk != project_pk:
		return redirect("ticket_detail", pk=ticket.pk)
	if request.method == "POST":
		TicketActivity.objects.create(ticket=ticket, actor=request.user,
			action=TicketActivity.Action.TICKET_DELETED)
		title = ticket.title
		ticket.delete()
		messages.success(request, f"Ticket '{title}' deleted.")
		return redirect("ticket_list")
	return render(request, "tracking/ticket_confirm_delete.html", {
		"title": f"Delete ticket — {ticket.title}",
		"ticket": ticket,
	})


@login_required
def ticket_attachment_upload(request: HttpRequest, pk: int) -> HttpResponseBase:
	ticket = get_object_or_404(Ticket, pk=pk)
	if request.method == "POST":
		form = AttachmentForm(request.POST, request.FILES)
		if form.is_valid():
			attachment = form.save(commit=False)
			attachment.ticket = ticket
			_, ext = attachment.name.rsplit(".", 1) if "." in attachment.name else (attachment.name, "")
			attachment.mime_type = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
				"pdf": "application/pdf", "txt": "text/plain", "log": "text/plain",
				"json": "application/json"}.get(ext.lower(), "application/octet-stream")
			attachment.save()
			TicketActivity.objects.create(ticket=ticket, actor=request.user,
				action=TicketActivity.Action.ATTACHMENT_ADDED,
				new_value=attachment.name)
			messages.success(request, "Attachment uploaded.")
			return redirect("ticket_detail", pk=ticket.pk)
	return redirect("ticket_detail", pk=ticket.pk)


@login_required
@require_POST
def ticket_attachment_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
	attachment = get_object_or_404(Attachment, pk=pk)
	ticket = attachment.ticket
	TicketActivity.objects.create(ticket=ticket, actor=request.user,
		action=TicketActivity.Action.ATTACHMENT_REMOVED,
		new_value=attachment.name)
	attachment.file.delete()
	attachment.delete()
	messages.success(request, "Attachment deleted.")
	return redirect("ticket_detail", pk=ticket.pk)


@login_required
def ticket_attachment_serve(request: HttpRequest, pk: int, attachment_pk: int) -> HttpResponseBase:
	attachment = get_object_or_404(Attachment, pk=attachment_pk)
	try:
		with open(attachment.file.path, "rb") as f:
			response = HttpResponse(f.read(), content_type=attachment.mime_type)
		response["Content-Disposition"] = f'inline; filename="{attachment.name}"'
		return response
	except (FileNotFoundError, ValueError) as e:
		messages.error(request, "Attachment file not found.")
		return redirect("ticket_detail", pk=attachment.ticket.pk)


@login_required
def version_create(request: HttpRequest, project_pk: int) -> HttpResponseBase:
	"""Create a new version for a project."""
	project = get_object_or_404(Project, pk=project_pk)
	from .forms import VersionForm as VersionCreateForm
	if request.method == "POST":
		form = VersionCreateForm(request.POST, project=project, data=request.POST)
		if form.is_valid():
			version = form.save(commit=False)
			version.project = project
			version.save()
			messages.success(request, f"Version '{version.name}' created.")
			return redirect("releases", project=project.key)
	else:
		form = VersionCreateForm(project=project)
	return render(request, "tracking/version_form.html", {
		"title": f"New version — {project.key}",
		"form": form,
		"project": project,
	})


@login_required
def version_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Edit an existing version."""
	version = get_object_or_404(Version, pk=pk)
	project = version.project
	from .forms import VersionForm as VersionEditForm
	if request.method == "POST":
		form = VersionEditForm(request.POST, instance=version, project=project)
		if form.is_valid():
			version = form.save()
			messages.success(request, f"Version '{version.name}' updated.")
			return redirect("releases", project=project.key)
	else:
		form = VersionEditForm(instance=version, project=project)
	return render(request, "tracking/version_form.html", {
		"title": f"Edit version — {project.key}",
		"form": form,
		"project": project,
		"version": version,
	})


@login_required
def version_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Delete a version."""
	version = get_object_or_404(Version, pk=pk)
	project = version.project
	if request.method == "POST":
		version.delete()
		messages.success(request, f"Version '{version.name}' deleted.")
		return redirect("releases", project=project.key)
	return render(request, "tracking/version_delete.html", {
		"title": f"Delete version — {project.key}",
		"project": project,
		"version": version,
	})


@login_required
def release_notes(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Generate and display release notes for a version."""
	version = get_object_or_404(Version, pk=pk)
	project = version.project
	notes = version.release_notes()
	markdown_html = render_markdown(notes, escape=True) if notes else ""
	tickets = list(version.affected_tickets.filter(
		fix_version=version, state=Ticket.State.RESOLVED
	).select_related("project", "assignee").order_by("type", "pk"))
	by_type: dict[str, list[Ticket]] = {}
	for t in tickets:
		by_type.setdefault(t.get_type_display(), []).append(t)
	return render(request, "tracking/release_notes.html", {
		"title": f"Release Notes — {version}",
		"version": version,
		"project": project,
		"markdown_html": markdown_html,
		"tickets": tickets,
		"by_type": by_type,
	})


@login_required
def version_roadmap(request: HttpRequest, project_pk: int) -> HttpResponseBase:
	"""Display a version roadmap / timeline for a project."""
	project = get_object_or_404(Project, pk=project_pk)
	projects = Project.objects.annotate(ticket_count=Count("tickets")).order_by("key")

	def sort_key(item):
		rd = item.get("release_date")
		td = item.get("target_date")
		cd = item.get("created_at")
		if rd is not None:
			return (rd, item["is_archived"])
		elif td is not None:
			return (td, item["is_archived"])
		return (cd, item["is_archived"])

	versions = project.versions.annotate(
		ticket_count=Count("affected_tickets__fix_version")
	).all()
	items = []
	for v in versions:
		items.append({
			"name": v.name,
			"target_date": v.target_date,
			"release_date": v.release_date,
			"created_at": v.created_at,
			"is_released": v.is_released,
			"is_active": v.is_active,
			"is_planned": v.is_planned,
			"is_archived": v.archived,
			"ticket_count": v.ticket_count,
		})
	items.sort(key=sort_key)
	return render(request, "tracking/version_roadmap.html", {
		"title": f"Roadmap — {project.key}",
		"project": project,
		"items": items,
		"projects": projects,
	})


def _build_tickets_queryset(request: HttpRequest) -> models.QuerySet[Ticket]:
	"""Re-build the filtered ticket queryset from the current GET params."""
	tickets = Ticket.objects.select_related("project", "assignee").prefetch_related("components", "labels")

	query = request.GET.get("q")
	if query:
		tickets = tickets.filter(
			Q(title__icontains=query) | Q(description__icontains=query)
		)

	project_key = request.GET.get("project")
	if project_key:
		tickets = tickets.filter(project__key=project_key)

	state = request.GET.get("state")
	if state:
		tickets = tickets.filter(state=state)

	component = request.GET.get("component")
	if component:
		tickets = tickets.filter(components__name=component)

	label = request.GET.get("label")
	if label:
		tickets = tickets.filter(labels__name=label)

	fix_version = request.GET.get("fix_version")
	if fix_version:
		tickets = tickets.filter(fix_version__pk=fix_version)

	assignee = request.GET.get("assignee")
	if assignee == "me":
		tickets = tickets.filter(assignee=request.user)
	elif assignee == "unassigned":
		tickets = tickets.filter(assignee__isnull=True)
	elif assignee:
		tickets = tickets.filter(assignee__pk=assignee)

	tickets = tickets.order_by("-updated_at")
	return tickets


@login_required
@require_POST
def ticket_bulk_action(request: HttpRequest) -> HttpResponseBase:
	"""Apply a bulk action to selected tickets from the ticket list."""
	ticket_ids_str = request.POST.get("ticket_ids", "")
	if not ticket_ids_str.strip():
		messages.warning(request, "No tickets selected.")
		return redirect("ticket_list")

	# Parse ticket IDs and fetch
	id_list = [int(x) for x in ticket_ids_str.split(",") if x.strip()]
	if not id_list:
		messages.warning(request, "No valid tickets selected.")
		return redirect("ticket_list")

	selected_tickets = list(Ticket.objects.filter(pk__in=id_list).order_by("pk"))
	if len(selected_tickets) != len(id_list):
		messages.warning(request, "Some selected tickets do not exist.")
		return redirect("ticket_list")

	if not selected_tickets:
		messages.warning(request, "No tickets selected.")
		return redirect("ticket_list")

	project = selected_tickets[0].project

	from .forms import BulkActionForm
	form = BulkActionForm(request.POST, project=project, request=request)

	if not form.is_valid():
		for field, errors in form.errors.items():
			for error in errors:
				messages.error(request, error)
		return redirect("ticket_list")

	action = form.cleaned_data["action"]
	items = form.cleaned_data["tickets"]
	success_count = 0
	err_count = 0

	if action == "transition":
		new_state = form.cleaned_data["state"]
		for ticket in items:
			try:
				old_state = ticket.state
				ticket.state = new_state
				ticket.save(update_fields=["state", "updated_at"])
				TicketActivity.objects.create(ticket=ticket, actor=request.user,
					action=TicketActivity.Action.STATE_CHANGED,
					old_value=old_state, new_value=ticket.state)
				success_count += 1
			except Exception:
				err_count += 1
		messages.success(request, f"Moved {success_count} ticket{'' if success_count == 1 else 's'} to '{Ticket.State(new_state).label}'."
			"{}" .format(f" {err_count} failed." if err_count else ""))

	elif action == "reassign":
		new_assignee = form.cleaned_data["assignee"]
		for ticket in items:
			try:
				old_assignee = ticket.assignee
				ticket.assignee = new_assignee
				ticket.save(update_fields=["assignee", "updated_at"])
				TicketActivity.objects.create(ticket=ticket, actor=request.user,
					action=TicketActivity.Action.TITLE_CHANGED,
					old_value=str(old_assignee), new_value=str(new_assignee))
				success_count += 1
			except Exception:
				err_count += 1
		messages.success(request, f"Reassigned {success_count} ticket{'' if success_count == 1 else 's'}."
			"{}" .format(f" {err_count} failed." if err_count else ""))

	elif action == "delete":
		# Record activities before deleting
		for ticket in items:
			try:
				TicketActivity.objects.create(ticket=ticket, actor=request.user,
					action=TicketActivity.Action.TICKET_DELETED)
				title = ticket.title
				ticket.delete()
				success_count += 1
			except Exception:
				err_count += 1
		messages.success(request, f"Deleted {success_count} ticket{'' if success_count == 1 else 's'}."
			"{}" .format(f" {err_count} failed." if err_count else ""))

	elif action == "labels":
		labels_to_add = form.cleaned_data["labels"]
		if not labels_to_add:
			messages.warning(request, "No labels selected.")
			return redirect("ticket_list")
		for ticket in items:
			try:
				old_labels = set(ticket.labels.values_list("pk", flat=True))
				ticket.labels.add(*labels_to_add)
				new_labels = set(ticket.labels.values_list("pk", flat=True))
				added = new_labels - old_labels
				for lbl_pk in added:
					lbl = labels_to_add.filter(pk=lbl_pk).first()
					if lbl:
						TicketActivity.objects.create(ticket=ticket, actor=request.user,
							action=TicketActivity.Action.LABEL_ADDED,
							field_name="label", new_value=lbl.name)
				success_count += 1
			except Exception:
				err_count += 1
		messages.success(request, f"Added labels to {success_count} ticket{'' if success_count == 1 else 's'}."
			"{}" .format(f" {err_count} failed." if err_count else ""))

	elif action == "components":
		components_to_add = form.cleaned_data["components"]
		if not components_to_add:
			messages.warning(request, "No components selected.")
			return redirect("ticket_list")
		for ticket in items:
			try:
				old_cmp = set(ticket.components.values_list("pk", flat=True))
				ticket.components.add(*components_to_add)
				new_cmp = set(ticket.components.values_list("pk", flat=True))
				added = new_cmp - old_cmp
				for cmp_pk in added:
					cmp = components_to_add.filter(pk=cmp_pk).first()
					if cmp:
						TicketActivity.objects.create(ticket=ticket, actor=request.user,
							action=TicketActivity.Action.COMPONENT_ADDED,
							field_name="component", new_value=cmp.name)
				success_count += 1
			except Exception:
				err_count += 1
		messages.success(request, f"Added components to {success_count} ticket{'' if success_count == 1 else 's'}."
			"{}" .format(f" {err_count} failed." if err_count else ""))

	elif action == "sprint":
		sprint = form.cleaned_data["sprint"]
		for ticket in items:
			try:
				old_sprint = ticket.sprint_id
				ticket.sprint = sprint
				ticket.save(update_fields=["sprint", "updated_at"])
				new_sprint_name = sprint.name if sprint else "(backlog)"
				TicketActivity.objects.create(ticket=ticket, actor=request.user,
					action=TicketActivity.Action.SPRINT_CHANGED,
					old_value=str(old_sprint), new_value=new_sprint_name)
				success_count += 1
			except Exception:
				err_count += 1
		messages.success(request, f"Moved {success_count} ticket{'' if success_count == 1 else 's'} to sprint."
			"{}" .format(f" {err_count} failed." if err_count else ""))

	return redirect("ticket_list")


# ── Health check ──────────────────────────────────────────────────────────────


def health_check(request: HttpRequest) -> HttpResponse:
	"""Minimal health-check endpoint.

	A Pok health probe should GET this path:  the application returns 200 with
	``{"status": "ok"}`` when the DB is reachable; otherwise 503.

	Unlike the rest of the views, this call is *not* login-required.
	"""
	try:
		Project.objects.aggregate(_ok_count=Count("id"))["_ok_count"]
	except Exception:
		return JsonResponse({"status": "error"}, status=503)
	return JsonResponse({"status": "ok"})
