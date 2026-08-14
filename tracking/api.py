"""Lightweight JSON REST API for the tracking app.

Built with plain Django (no DRF) to stay dependency-free and consistent with
the rest of the project. Intended to be consumed programmatically — e.g. by an
MCP server that exposes tickets/projects as tools to an AI agent.

All endpoints speak JSON and are CSRF-exempt (they are not browser-form driven).
The state machine is *not* re-implemented here: state changes go through
``Ticket.can_transition_to`` exactly like the HTML views do.

An OpenAPI 3.1.0 schema is available at ``/tracking/api/schema/`` for use with
Swagger UI, ReDoc, or any OpenAPI-compatible tool.

Routes are wired in ``tracking/urls.py`` under ``/tracking/api/``.
"""
from __future__ import annotations

import hmac
import json
from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db.models import Q
from django.db.models.query import QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.http.response import HttpResponseBase
from django.shortcuts import get_object_or_404
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Attachment, Comment, Component, Label, Project, Sprint, Ticket, TicketActivity, TicketRelation

if TYPE_CHECKING:
  from typing import ParamSpec

  _P = ParamSpec("_P")


# --- Authentication --------------------------------------------------------

def _token_ok(request: HttpRequest) -> bool:
	"""True if the request carries the configured API bearer token."""
	expected = settings.TRACKING_API_TOKEN
	if not expected:
		return False
	header = request.META.get("HTTP_AUTHORIZATION", "")
	provided = ""
	if header.startswith("Bearer "):
		provided = header[len("Bearer "):].strip()
	else:
		provided = request.META.get("HTTP_X_API_TOKEN", "").strip()
	# Constant-time compare to avoid leaking the token via timing.
	return bool(provided) and hmac.compare_digest(provided, expected)


def require_api_auth(view: Callable[..., HttpResponseBase]) -> Callable[..., HttpResponseBase]:
	"""Allow either a logged-in session or a valid API token.

	MCP clients authenticate with ``Authorization: Bearer <TRACKING_API_TOKEN>``
	(or an ``X-API-Token`` header); browser sessions work too for convenience.
	"""

	@wraps(view)
	def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
		if request.user.is_authenticated or _token_ok(request):
			return view(request, *args, **kwargs)
		response = JsonResponse({"error": "Authentication required."}, status=401)
		response["WWW-Authenticate"] = "Bearer"
		return response

	return wrapper


# --- Serialization helpers -------------------------------------------------

def serialize_project(project: Project) -> dict[str, Any]:
	return {
		"key": project.key,
		"name": project.name,
		"description": project.description,
		"created_at": project.created_at.isoformat(),
	}


def serialize_ticket(ticket: Ticket) -> dict[str, Any]:
	return {
		"id": ticket.pk,
		"project": ticket.project.key,
		"title": ticket.title,
		"description": ticket.description,
		"type": ticket.type,
		"type_display": ticket.get_type_display(),
		"state": ticket.state,
		"state_display": ticket.get_state_display(),
		"priority": ticket.priority,
		"priority_display": ticket.get_priority_display(),
		"estimation": ticket.estimation,
		"parent_epic": ticket.parent_epic_id,
		"parent_epic_display": ticket.epic_display,
		"reporter": str(ticket.reporter) if ticket.reporter else None,
		"assignee": str(ticket.assignee) if ticket.assignee else None,
		"components": [
			serialize_component(c) for c in ticket.components.all()
		],
		"labels": [
			serialize_label(l) for l in ticket.labels.all()
		],
		"relations": [
			serialize_relation(r)
			for r in TicketRelation.objects.filter(
				(Q(subject=ticket) | Q(target=ticket))
			).select_related("subject", "target")
		],
		"allowed_transitions": [s.value for s in ticket.allowed_transitions()],
		"comments": [
			serialize_comment(c)
			for c in ticket.comments.select_related("author").all()
		],
		"due_date": ticket.due_date.isoformat() if ticket.due_date else None,
		"created_at": ticket.created_at.isoformat(),
		"updated_at": ticket.updated_at.isoformat(),
	}


def serialize_relation(relation: TicketRelation) -> dict[str, Any]:
	return {
		"id": relation.pk,
		"subject": relation.subject.pk,
		"target": relation.target.pk,
		"relation_type": relation.relation_type,
		"relation_type_display": relation.get_relation_type_display(),
		"created_at": relation.created_at.isoformat(),
	}


def serialize_comment(comment: Comment) -> dict[str, Any]:
	return {
		"id": comment.pk,
		"ticket": comment.ticket.pk,
		"body": comment.body,
		"author": str(comment.author) if comment.author else None,
		"created_at": comment.created_at.isoformat(),
		"updated_at": comment.updated_at.isoformat(),
	}


def serialize_component(component: Component) -> dict[str, Any]:
	return {
		"id": component.pk,
		"project": component.project.key,
		"name": component.name,
		"description": component.description,
		"created_at": component.created_at.isoformat(),
	}


def serialize_label(label: Label) -> dict[str, Any]:
	return {
		"id": label.pk,
		"project": label.project.key,
		"name": label.name,
		"color": label.color,
		"description": label.description,
		"created_at": label.created_at.isoformat(),
	}


def serialize_attachment(attachment: Attachment) -> dict[str, Any]:
	from django.conf import settings
	return {
		"id": attachment.pk,
		"ticket": attachment.ticket.pk,
		"name": attachment.name,
		"mime_type": attachment.mime_type,
		"url": f"{settings.MEDIA_URL}attachments/{attachment.ticket.project.key}/{attachment.ticket.pk}/{attachment.file_extension}/{attachment.name}",
		"created_at": attachment.created_at.isoformat(),
	}


def _parse_json(request: HttpRequest) -> dict[str, Any]:
	"""Return the parsed JSON body, or raise ``ValueError`` on bad input."""
	if not request.body:
		return {}
	return json.loads(request.body)


def _error(message: str, status: int = 400, **extra: Any) -> JsonResponse:
	return JsonResponse({"error": message, **extra}, status=status)


# --- Meta / discovery ------------------------------------------------------

@require_api_auth
@require_http_methods(["GET"])
def meta(request: HttpRequest) -> JsonResponse:
	"""Expose enums and the state machine so a client can self-describe.

	Handy for MCP: an agent can read this once to learn valid values and the
	allowed state-transition graph before creating or moving tickets.
	"""
	return JsonResponse({
		"types": [{"value": t.value, "label": str(t.label)} for t in Ticket.Type],
		"states": [{"value": s.value, "label": str(s.label)} for s in Ticket.State],
		"priorities": [
			{"value": p.value, "label": str(p.label)} for p in Ticket.Priority
		],
		"relations": [
			{"value": r.value, "label": str(r.label)}
			for r in Ticket.RelationType
		],
		"transitions": {
			state.value: [s.value for s in targets]
			for state, targets in Ticket.TRANSITIONS.items()
		},
	})


# --- Projects --------------------------------------------------------------

@csrf_exempt
@require_api_auth
@require_http_methods(["GET", "POST"])
def project_collection(request: HttpRequest) -> HttpResponseBase:
	if request.method == "GET":
		projects = Project.objects.all().order_by("key")
		return JsonResponse(
			{"projects": [serialize_project(p) for p in projects]}
		)

	# POST -> create
	try:
		data = _parse_json(request)
	except (ValueError, json.JSONDecodeError):
		return _error("Request body must be valid JSON.")

	key = (data.get("key") or "").strip().upper()
	name = (data.get("name") or "").strip()
	if not key or not name:
		return _error("Both 'key' and 'name' are required.")
	if Project.objects.filter(key=key).exists():
		return _error(f"Project with key '{key}' already exists.", status=409)

	project = Project.objects.create(
		key=key, name=name, description=data.get("description", "")
	)
	return JsonResponse(serialize_project(project), status=201)


@require_api_auth
@require_http_methods(["GET"])
def project_detail(request: HttpRequest, key: str) -> JsonResponse:
	project = get_object_or_404(Project, key=key.upper())
	return JsonResponse(serialize_project(project))


# --- Tickets ---------------------------------------------------------------

@csrf_exempt
@require_api_auth
@require_http_methods(["GET", "POST"])
def ticket_collection(request: HttpRequest) -> HttpResponseBase:
	if request.method == "GET":
		tickets = Ticket.objects.select_related("project", "assignee", "reporter")
		project_key = request.GET.get("project")
		if project_key:
			tickets = tickets.filter(project__key=project_key.upper())
		state = request.GET.get("state")
		if state:
			tickets = tickets.filter(state=state)
		assignee = request.GET.get("assignee")
		if assignee == "me":
			tickets = tickets.filter(assignee=request.user)
		elif assignee == "unassigned":
			tickets = tickets.filter(assignee__isnull=True)
		elif assignee:
			tickets = tickets.filter(assignee__pk=assignee)
		component = request.GET.get("component")
		if component:
			tickets = tickets.filter(components__name=component)
		label = request.GET.get("label")
		if label:
			tickets = tickets.filter(labels__name=label)
		return JsonResponse(
			{"tickets": [serialize_ticket(t) for t in tickets]}
		)

	# POST -> create
	try:
		data = _parse_json(request)
	except (ValueError, json.JSONDecodeError):
		return _error("Request body must be valid JSON.")

	project_key = (data.get("project") or "").strip().upper()
	title = (data.get("title") or "").strip()
	if not project_key or not title:
		return _error("Both 'project' and 'title' are required.")

	try:
		project = Project.objects.get(key=project_key)
	except Project.DoesNotExist:
		return _error(f"Unknown project '{project_key}'.", status=404)

	ticket_type = data.get("type", Ticket.Type.TASK)
	if ticket_type not in Ticket.Type.values:
		return _error(f"Invalid type '{ticket_type}'.")

	priority = data.get("priority", Ticket.Priority.MEDIUM)
	if priority not in Ticket.Priority.values:
		return _error(f"Invalid priority '{priority}'.")

	ticket = Ticket(
		project=project,
		title=title,
		description=data.get("description", ""),
		type=ticket_type,
		priority=priority,
		estimation=data.get("estimation"),
		due_date=data.get("due_date") or None,
	)
	if request.user.is_authenticated:
		ticket.reporter = request.user
	ticket.save()
	TicketActivity.objects.create(ticket=ticket, actor=request.user if request.user.is_authenticated else None,
		action=TicketActivity.Action.TICKET_CREATED)

	# Set components and labels if provided
	component_names = data.get("components", [])
	if component_names:
		for name in component_names:
			try:
				component = Component.objects.get(project=project, name=name)
				ticket.components.add(component)
			except Component.DoesNotExist:
				pass  # silently ignore unknown component names

	label_names = data.get("labels", [])
	if label_names:
		for name in label_names:
			try:
				label = Label.objects.get(project=project, name=name)
				ticket.labels.add(label)
			except Label.DoesNotExist:
				pass  # silently ignore unknown label names

	ticket.save()
	return JsonResponse(serialize_ticket(ticket), status=201)


@csrf_exempt
@require_api_auth
@require_http_methods(["GET", "PATCH"])
def ticket_detail(request: HttpRequest, pk: int) -> HttpResponseBase:
	ticket = get_object_or_404(
		Ticket.objects.select_related("project", "assignee", "reporter"), pk=pk
	)
	if request.method == "GET":
		return JsonResponse(serialize_ticket(ticket))

	# PATCH -> partial update. State is intentionally excluded; use /transition/.
	try:
		data = _parse_json(request)
	except (ValueError, json.JSONDecodeError):
		return _error("Request body must be valid JSON.")

	if "state" in data:
		return _error(
			"Use the /transition/ endpoint to change 'state'.", status=400
		)

	updatable = {"title", "description", "type", "estimation", "priority", "assignee", "parent_epic", "due_date", "sprint"}
	if "assignee" in data:
		assignee_value = data["assignee"]
		if assignee_value is not None and assignee_value != "":
			from django.contrib.auth import get_user_model
			try:
				data["assignee"] = get_user_model().objects.get(username=assignee_value)
			except get_user_model().DoesNotExist:
				return _error(f"Unknown user '{assignee_value}'.")
		else:
			data["assignee"] = None
	if "due_date" in data:
		due_value = data.get("due_date")
		if due_value is None or due_value == "":
			data["due_date"] = None
	if "parent_epic" in data:
		epic_value = data["parent_epic"]
		if epic_value is not None:
			try:
				data["parent_epic"] = Ticket.objects.get(pk=epic_value)
			except Ticket.DoesNotExist:
				return _error(f"Parent epic ticket not found.", status=404)
		else:
			data["parent_epic"] = None
	changed: list[str] = []
	for field in updatable & set(data):
		value = data[field]
		if field == "type" and value not in Ticket.Type.values:
			return _error(f"Invalid type '{value}'.")
		if field == "priority" and value not in Ticket.Priority.values:
			return _error(f"Invalid priority '{value}'.")
		if field == "sprint":
			if value is not None:
				try:
					value = Sprint.objects.get(pk=value)
				except Sprint.DoesNotExist:
					return _error(f"Unknown sprint id '{value}'.")
		setattr(ticket, field, value)
		changed.append(field)

	# Handle labels (ManyToMany)
	if "labels" in data:
		label_names = data.get("labels", [])
		ticket.labels.clear()
		for name in label_names:
			try:
				label = Label.objects.get(project=ticket.project, name=name)
				ticket.labels.add(label)
			except Label.DoesNotExist:
				pass  # silently ignore unknown label names

	# Handle components (ManyToMany)
	if "components" in data:
		component_names = data.get("components", [])
		ticket.components.clear()
		for name in component_names:
			try:
				component = Component.objects.get(project=ticket.project, name=name)
				ticket.components.add(component)
			except Component.DoesNotExist:
				pass  # silently ignore unknown component names

	if changed:
		user = request.user if request.user.is_authenticated else None
		for field in changed:
			val = data.get(field)
			old_val = str(getattr(ticket, field, ''))
			if field == "priority":
				old_val = ticket.get_priority_display()
			elif field == "type":
				old_val = ticket.get_type_display()
			new_val = str(val) if val is not None else ""
			if old_val or new_val:
				TicketActivity.objects.create(ticket=ticket, actor=user,
					action=TicketActivity.Action.STATE_CHANGED,
					field_name=field, old_value=old_val, new_value=new_val)
		ticket.save(update_fields=[*changed, "updated_at"])
	return JsonResponse(serialize_ticket(ticket))


@csrf_exempt
@require_api_auth
@require_http_methods(["POST"])
def ticket_transition(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Move a ticket to a new state, honouring ``Ticket.TRANSITIONS``."""
	ticket = get_object_or_404(Ticket, pk=pk)
	try:
		data = _parse_json(request)
	except (ValueError, json.JSONDecodeError):
		return _error("Request body must be valid JSON.")

	new_state = data.get("state")
	if not new_state:
		return _error("Field 'state' is required.")
	if new_state not in Ticket.State.values:
		return _error(f"Invalid state '{new_state}'.")
	if not ticket.can_transition_to(new_state):
		return _error(
			f"Cannot transition from '{ticket.state}' to '{new_state}'.",
			status=409,
			allowed_transitions=[s.value for s in ticket.allowed_transitions()],
		)

	old_state = ticket.state
	ticket.state = new_state
	ticket.save(update_fields=["state", "updated_at"])
	user = request.user if request.user.is_authenticated else None
	TicketActivity.objects.create(ticket=ticket, actor=user,
		action=TicketActivity.Action.STATE_CHANGED,
		old_value=old_state, new_value=new_state)
	return JsonResponse(serialize_ticket(ticket))


# --- Comments --------------------------------------------------------------

@csrf_exempt
@require_api_auth
@require_http_methods(["GET", "POST"])
def comment_collection(request: HttpRequest) -> HttpResponseBase:
	"""List or create comments on a ticket."""
	ticket_pk = request.GET.get("ticket")
	if not ticket_pk:
		return _error("Query parameter 'ticket' is required.")
	ticket = get_object_or_404(Ticket, pk=ticket_pk)

	if request.method == "GET":
		comments = Comment.objects.select_related("author").filter(ticket=ticket)
		return JsonResponse(
			{"comments": [serialize_comment(c) for c in comments]}
		)

	# POST -> create
	try:
		data = _parse_json(request)
	except (ValueError, json.JSONDecodeError):
		return _error("Request body must be valid JSON.")

	body = (data.get("body") or "").strip()
	if not body:
		return _error("Field 'body' is required.")

	comment = Comment.objects.create(
		ticket=ticket,
		body=body,
		author=request.user if request.user.is_authenticated else None,
	)
	user = request.user if request.user.is_authenticated else None
	TicketActivity.objects.create(ticket=ticket, actor=user,
		action=TicketActivity.Action.COMMENT_ADDED)
	return JsonResponse(serialize_comment(comment), status=201)


# --- Components -------------------------------------------------------------

@csrf_exempt
@require_api_auth
@require_http_methods(["GET", "POST"])
def component_collection(request: HttpRequest) -> HttpResponseBase:
	"""List or create components for a project."""
	project_key = request.GET.get("project")
	if not project_key:
		return _error("Query parameter 'project' is required.")
	project = get_object_or_404(Project, key=project_key.upper())

	if request.method == "GET":
		components = project.components.all()
		return JsonResponse(
			{"components": [serialize_component(c) for c in components]}
		)

	# POST -> create
	try:
		data = _parse_json(request)
	except (ValueError, json.JSONDecodeError):
		return _error("Request body must be valid JSON.")

	name = (data.get("name") or "").strip()
	if not name:
		return _error("Field 'name' is required.")
	if Component.objects.filter(project=project, name=name).exists():
		return _error(f"Component '{name}' already exists in project '{project.key}'.", status=409)

	component = Component.objects.create(
		project=project,
		name=name,
		description=data.get("description", ""),
	)
	return JsonResponse(serialize_component(component), status=201)


@csrf_exempt
@require_api_auth
@require_http_methods(["GET", "PATCH", "DELETE"])
def component_detail(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Retrieve, update, or delete a single component."""
	component = get_object_or_404(Component, pk=pk)

	if request.method == "GET":
		return JsonResponse(serialize_component(component))

	if request.method == "PATCH":
		try:
			data = _parse_json(request)
		except (ValueError, json.JSONDecodeError):
			return _error("Request body must be valid JSON.")

		changed: list[str] = []
		for field in ("name", "description"):
			if field in data:
				setattr(component, field, data[field])
				changed.append(field)

		if changed:
			component.save(update_fields=changed)
		return JsonResponse(serialize_component(component))

	# DELETE
	component.delete()
	return JsonResponse({"status": "deleted"})


# --- Labels ------------------------------------------------------------------

@csrf_exempt
@require_api_auth
@require_http_methods(["GET", "POST"])
def label_collection(request: HttpRequest) -> HttpResponseBase:
	"""List or create labels for a project."""
	project_key = request.GET.get("project")
	if not project_key:
		return _error("Query parameter 'project' is required.")
	project = get_object_or_404(Project, key=project_key.upper())

	if request.method == "GET":
		labels = project.labels.all()
		return JsonResponse(
			{"labels": [serialize_label(l) for l in labels]}
		)

	# POST -> create
	try:
		data = _parse_json(request)
	except (ValueError, json.JSONDecodeError):
		return _error("Request body must be valid JSON.")

	name = (data.get("name") or "").strip()
	if not name:
		return _error("Field 'name' is required.")
	if Label.objects.filter(project=project, name=name).exists():
		return _error(f"Label '{name}' already exists in project '{project.key}'.", status=409)

	label = Label.objects.create(
		project=project,
		name=name,
		color=data.get("color", "secondary"),
		description=data.get("description", ""),
	)
	return JsonResponse(serialize_label(label), status=201)


# --- Attachments -----------------------------------------------------------

@csrf_exempt
@require_api_auth
@require_http_methods(["GET", "POST"])
def attachment_collection(request: HttpRequest) -> HttpResponseBase:
	"""List or upload attachments on a ticket."""
	ticket_pk = request.GET.get("ticket")
	if not ticket_pk:
		return _error("Query parameter 'ticket' is required.")
	ticket = get_object_or_404(Ticket, pk=ticket_pk)

	if request.method == "GET":
		attachments = ticket.attachments.all()
		return JsonResponse(
			{"attachments": [serialize_attachment(a) for a in attachments]}
		)

	# POST -> upload
	file = request.FILES.get("file")
	if not file:
		return _error("Field 'file' is required.")

	allowed_exts = {"png", "jpg", "jpeg", "pdf", "txt", "log", "json"}
	name_lower = file.name.lower()
	ext = name_lower.rsplit(".", 1)[-1] if "." in name_lower else ""
	if ext not in allowed_exts:
		return _error(f"File type '.{ext}' is not allowed. Allowed: {', '.join(sorted(allowed_exts))}")

	mime_map = {
		"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
		"pdf": "application/pdf", "txt": "text/plain", "log": "text/plain",
		"json": "application/json",
	}
	attachment = Attachment.objects.create(
		ticket=ticket,
		name=file.name,
		file=file,
		mime_type=mime_map.get(ext, "application/octet-stream"),
	)
	user = request.user if request.user.is_authenticated else None
	TicketActivity.objects.create(ticket=ticket, actor=user,
		action=TicketActivity.Action.ATTACHMENT_ADDED,
		new_value=file.name)
	return JsonResponse(serialize_attachment(attachment), status=201)


@csrf_exempt
@require_api_auth
@require_http_methods(["GET", "DELETE"])
def attachment_detail(request: HttpRequest, pk: int) -> HttpResponseBase:
	attachment = get_object_or_404(Attachment, pk=pk)
	if request.method == "GET":
		return JsonResponse(serialize_attachment(attachment))
	# DELETE -> remove attachment
	if request.user.is_authenticated:
		TicketActivity.objects.create(ticket=attachment.ticket, actor=request.user,
			action=TicketActivity.Action.ATTACHMENT_REMOVED,
			new_value=attachment.name)
	attachment.file.delete()
	attachment.delete()
	return JsonResponse({"status": "deleted"})


# --- Sprints --------------------------------------------------------------

def serialize_sprint(sprint: Sprint) -> dict[str, Any]:
	"""Return a dict for a sprint."""
	return {
		"id": sprint.pk,
		"project": sprint.project.key,
		"name": sprint.name,
		"description": sprint.description,
		"start_date": sprint.start_date.isoformat() if sprint.start_date else None,
		"end_date": sprint.end_date.isoformat() if sprint.end_date else None,
		"order": sprint.order,
		"is_active": sprint.is_active,
		"created_at": sprint.created_at.isoformat(),
	}


@csrf_exempt
@require_api_auth
@require_http_methods(["GET"])
def sprint_collection(request: HttpRequest, project_key: str) -> JsonResponse:
	"""Return all sprints for a project."""
	project = get_object_or_404(Project, key=project_key.upper())
	return JsonResponse({
		"sprints": [
			serialize_sprint(s)
			for s in project.sprints.all()
		],
	})


@csrf_exempt
@require_api_auth
@require_http_methods(["GET"])
def active_sprint_tickets(request: HttpRequest, project_key: str) -> JsonResponse:
	"""Return the tickets of the project's active sprint.

	A project has at most one active sprint. When no sprint is active, this
	returns ``sprint: null`` and an empty ``tickets`` list.
	"""
	project = get_object_or_404(Project, key=project_key.upper())
	sprint = project.sprints.filter(is_active=True).first()
	tickets: list[dict[str, Any]] = []
	if sprint is not None:
		ticket_qs = Ticket.objects.filter(sprint=sprint).select_related(
			"project", "assignee", "reporter"
		)
		tickets = [serialize_ticket(t) for t in ticket_qs]
	return JsonResponse({
		"sprint": serialize_sprint(sprint) if sprint else None,
		"tickets": tickets,
	})


@csrf_exempt
@require_api_auth
@require_http_methods(["POST"])
def sprint_create(request: HttpRequest, project_key: str) -> HttpResponseBase:
	"""Create a sprint in a project."""
	project = get_object_or_404(Project, key=project_key.upper())
	try:
		body = json.loads(request.body)
	except (ValueError, KeyError):
		return _error("Request body must be valid JSON and must include 'name'.")
	name = body.get("name", "").strip()
	if not name:
		return _error("'name' is required.")
	if Sprint.objects.filter(project=project, name=name).exists():
		return _error(f"A sprint named '{name}' already exists.", status=409)
	sprint = Sprint(
		project=project,
		name=name,
		description=body.get("description", ""),
		start_date=body.get("start_date"),
		end_date=body.get("end_date"),
		order=body.get("order", 0),
		is_active=bool(body.get("is_active", False)),
	)
	sprint.save()
	return JsonResponse(serialize_sprint(sprint), status=201)


@csrf_exempt
@require_api_auth
@require_http_methods(["GET", "PATCH", "DELETE"])
def sprint_detail(request: HttpRequest, pk: int) -> HttpResponseBase:
	"""Retrive, update, or delete a single sprint."""
	sprint = get_object_or_404(Sprint, pk=pk)
	if request.method == "GET":
		return JsonResponse(serialize_sprint(sprint))
	if request.method == "PATCH":
		try:
			body = json.loads(request.body)
		except ValueError:
			return _error("Request body must be valid JSON.")
		for field in ("name", "description", "start_date", "end_date", "order", "is_active"):
			if field in body:
				setattr(sprint, field, body[field])
		sprint.save()
		return JsonResponse(serialize_sprint(sprint))
	# DELETE
	if sprint.is_backlog:
		return _error("Cannot delete the backlog pseudo-sprint.", status=403)
	sprint.delete()
	return JsonResponse({"status": "deleted"})


# --- Sprint Close --------------------------------------------------------

@csrf_exempt
@require_api_auth
@require_http_methods(["POST"])
def sprint_close(request: HttpRequest, project_key: str, sprint_pk: int) -> JsonResponse:
	"""Close the active sprint (deactivate and set end_date to today).

	Accepts optional JSON body with:
	- action: one of "backlog", "sprint", "keep" (default "backlog")
	- target_sprint: sprint id to move tickets to (required if action="sprint")
	"""
	project = get_object_or_404(Project, key=project_key.upper())
	sprint = get_object_or_404(Sprint, pk=sprint_pk, project=project)
	if sprint.is_backlog:
		return _error("Cannot close the backlog pseudo-sprint.", status=403)
	try:
		body = json.loads(request.body) if request.body else {}
	except ValueError:
		return _error("Request body must be valid JSON.")
	action = body.get("action", "backlog")
	if action not in ("backlog", "sprint", "keep"):
		return _error(f"Invalid action '{action}'. Must be backtrack, sprint, or keep.", status=400)
	target_sprint_id: int | None = None
	if action == "sprint":
		target_sprint_id = body.get("target_sprint")
		if not target_sprint_id:
			return _error("'target_sprint' is required when action is 'sprint'.", status=400)
		try:
			target_sprint = Sprint.objects.get(pk=target_sprint_id, project=project)
		except Sprint.DoesNotExist:
			return _error("Unknown target sprint.", status=404)
		if target_sprint.pk == sprint.pk:
			return _error("Cannot move tickets to the same sprint.", status=400)
	sprint.close_with_action(action, target_sprint_id)
	return JsonResponse(serialize_sprint(sprint))


# --- Relations ----------------------------------------------------------

@csrf_exempt
@require_api_auth
@require_http_methods(["POST"])
def ticket_relation_create(request: HttpRequest, ticket_id: int) -> HttpResponseBase:
	"""Create a relation from one ticket to another."""
	ticket = get_object_or_404(Ticket, pk=ticket_id)
	try:
		body = json.loads(request.body)
	except (ValueError, KeyError):
		return _error("Request body must be valid JSON and must include 'target_id' and 'relation_type'.")
	target_id = body.get("target_id")
	relation_type = body.get("relation_type", "").strip()
	if not target_id or not relation_type:
		return _error("'target_id' and 'relation_type' are required.")
	try:
		target = Ticket.objects.get(pk=target_id)
	except Ticket.DoesNotExist:
		return _error("Target ticket not found.", status=404)
	if target.project != ticket.project:
		return _error("Target ticket must be in the same project.", status=409)
	if TicketRelation.objects.filter(
		subject=ticket, target=target, relation_type=relation_type,
	).exists():
		return _error("This relation already exists.", status=409)
	if TicketRelation.objects.filter(
		subject=target, target=ticket, relation_type=relation_type,
	).exists():
		return _error("This relation already exists.", status=409)
	if relation_type not in dict(Ticket.RelationType.choices):
		return _error(f"Invalid relation type: {relation_type}", status=400)
	relation = TicketRelation.objects.create(
		subject=ticket, target=target, relation_type=relation_type,
	)
	user = request.user if request.user.is_authenticated else None
	TicketActivity.objects.create(ticket=ticket, actor=user,
		action=TicketActivity.Action.RELATION_ADDED,
		new_value=f"{target.pk}: {relation.get_relation_type_display()}")
	return JsonResponse(serialize_relation(relation), status=201)


@csrf_exempt
@require_api_auth
@require_http_methods(["DELETE"])
def ticket_relation_delete_api(request: HttpRequest, pk: int) -> JsonResponse:
	"""Delete a ticket relation by its ID."""
	relation = get_object_or_404(TicketRelation, pk=pk)
	ticket = relation.subject
	user = request.user if request.user.is_authenticated else None
	TicketActivity.objects.create(ticket=ticket, actor=user,
		action=TicketActivity.Action.RELATION_REMOVED,
		new_value=f"{relation.target.pk}: {relation.get_relation_type_display()}")
	rev_types = Ticket._REVERSE_LABELS or {}
	if relation.relation_type in rev_types:
		try:
			TicketRelation.objects.get(
				subject=relation.target,
				target=relation.subject,
				relation_type=rev_types[relation.relation_type],
			).delete()
		except TicketRelation.DoesNotExist:
			pass
	relation.delete()
	return JsonResponse({"status": "deleted"})


# --- OpenAPI Schema --------------------------------------------------------

def _schema() -> dict[str, Any]:
	"""Return a hand-written OpenAPI 3.1.0 schema for the tracking API.

	No DRF dependency — just plain Django, keeping alignment with the rest of the
	project's lightweight philosophy.
	"""

	def _path(url: str, methods: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
		return (url, methods)

	paths: dict[str, dict[str, Any]] = {
		"/tracking/api/meta/": {
			"get": {
				"summary": "Enum values and state-transition graph",
				"description": "Returns all ticket types, states, priorities, relation types, and the allowed state-transition graph so a client can self-describe.",
				"tags": ["Discovery"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Meta"}}},
					},
					"401": {"$ref": "#/components/responses/Unauthorized"},
				},
			},
		},
		"/tracking/api/projects/": {
			"get": {
				"summary": "List all projects",
				"tags": ["Projects"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ProjectList"}}},
					},
					"401": {"$ref": "#/components/responses/Unauthorized"},
				},
			},
			"post": {
				"summary": "Create a project",
				"tags": ["Projects"],
				"requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CreateProject"}}}},
				"responses": {
					"201": {
						"description": "Created",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Project"}}},
					},
					"400": {"description": "Bad request — key and name required."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"409": {"description": "Project key already exists."},
				},
			},
		},
		"/tracking/api/projects/{key}/": {
			"get": {
				"summary": "Retrieve a project by its key",
				"tags": ["Projects"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "key", "in": "path", "required": True, "schema": {"type": "string"}, "description": "Project key (e.g. 'SMT')"}],
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Project"}}},
					},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Project not found."},
				},
			},
		},
		"/tracking/api/tickets/": {
			"get": {
				"summary": "List tickets (filterable)",
				"description": "Filter by ``project``, ``state``, ``assignee`` (``me``/``unassigned`` or user ID), ``component``, and ``label``.",
				"tags": ["Tickets"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [
					{"name": "project", "in": "query", "schema": {"type": "string"}, "description": "Filter by project key."},
					{"name": "state", "in": "query", "schema": {"type": "string"}, "description": "Filter by ticket state value."},
					{"name": "assignee", "in": "query", "schema": {"type": "string"}, "description": "Filter by assignee username, ``me``, or ``unassigned``."},
					{"name": "component", "in": "query", "schema": {"type": "string"}, "description": "Filter by component name."},
					{"name": "label", "in": "query", "schema": {"type": "string"}, "description": "Filter by label name."},
				],
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/TicketList"}}},
					},
					"401": {"$ref": "#/components/responses/Unauthorized"},
				},
			},
			"post": {
				"summary": "Create a ticket",
				"tags": ["Tickets"],
				"requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CreateTicket"}}}},
				"responses": {
					"201": {
						"description": "Created",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Ticket"}}},
					},
					"400": {"description": "Bad request."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Project not found."},
				},
			},
		},
		"/tracking/api/tickets/{pk}/": {
			"get": {
				"summary": "Retrieve a ticket with relations, comments, and allowed transitions",
				"tags": ["Tickets"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "pk", "in": "path", "required": True, "schema": {"type": "integer"}, "description": "Ticket primary key."}],
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Ticket"}}},
					},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Ticket not found."},
				},
			},
			"patch": {
				"summary": "Partial update of a ticket (state excluded)",
				"description": "Use the **/transition/** endpoint to change ``state``.",
				"tags": ["Tickets"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "pk", "in": "path", "required": True, "schema": {"type": "integer"}, "description": "Ticket primary key."}],
				"requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/UpdateTicket"}}}},
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Ticket"}}},
					},
					"400": {"description": "Bad request (e.g. 'state' in body)."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Ticket not found."},
				},
			},
		},
		"/tracking/api/tickets/{pk}/transition/": {
			"post": {
				"summary": "Transition a ticket to a new state",
				"description": "Honours ``Ticket.TRANSITIONS``. Returns 409 with **allowed_transitions** when the move is invalid.",
				"tags": ["Tickets"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "pk", "in": "path", "required": True, "schema": {"type": "integer"}, "description": "Ticket primary key."}],
				"requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/TransitionTicket"}}}},
				"responses": {
					"200": {
						"description": "OK — ticket with new state.",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Ticket"}}},
					},
					"400": {"description": "Bad request."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Ticket not found."},
					"409": {"description": "Invalid transition."},
				},
			},
		},
		"/tracking/api/tickets/{ticket_id}/relations/add/": {
			"post": {
				"summary": "Create a relation between two tickets",
				"description": "Relations are **symmetric**: the reverse counterpart is auto-created. Tickets must be in the same project.",
				"tags": ["Tickets"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "ticket_id", "in": "path", "required": True, "schema": {"type": "integer"}, "description": "Subject ticket ID."}],
				"requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CreateRelation"}}}},
				"responses": {
					"201": {
						"description": "Created",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/TicketRelation"}}},
					},
					"400": {"description": "Invalid relation type."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Target ticket not found."},
					"409": {"description": "Related tickets must be in the same project, or relation already exists."},
				},
			},
		},
		"/tracking/api/comments/": {
			"get": {
				"summary": "List comments on a ticket",
				"tags": ["Comments"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "ticket", "in": "query", "required": True, "schema": {"type": "integer"}, "description": "Ticket primary key."}],
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/CommentList"}}},
					},
					"400": {"description": "Query parameter 'ticket' is required."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Ticket not found."},
				},
			},
			"post": {
				"summary": "Create a comment on a ticket",
				"tags": ["Comments"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "ticket", "in": "query", "required": True, "schema": {"type": "integer"}, "description": "Ticket primary key."}],
				"requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CreateComment"}}}},
				"responses": {
					"201": {
						"description": "Created",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Comment"}}},
					},
					"400": {"description": "Body is required."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Ticket not found."},
				},
			},
		},
		"/tracking/api/components/": {
			"get": {
				"summary": "List components for a project",
				"tags": ["Components"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "project", "in": "query", "required": True, "schema": {"type": "string"}, "description": "Project key."}],
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ComponentList"}}},
					},
					"400": {"description": "Query parameter 'project' is required."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Project not found."},
				},
			},
			"post": {
				"summary": "Create a component in a project",
				"tags": ["Components"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "project", "in": "query", "required": True, "schema": {"type": "string"}, "description": "Project key."}],
				"requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CreateComponent"}}}},
				"responses": {
					"201": {
						"description": "Created",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Component"}}},
					},
					"400": {"description": "Name is required."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"409": {"description": "Component already exists."},
				},
			},
		},
		"/tracking/api/components/{pk}/": {
			"get": {
				"summary": "Retrieve a component",
				"tags": ["Components"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "pk", "in": "path", "required": True, "schema": {"type": "integer"}}],
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Component"}}},
					},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Component not found."},
				},
			},
			"patch": {
				"summary": "Update a component",
				"tags": ["Components"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "pk", "in": "path", "required": True, "schema": {"type": "integer"}}],
				"requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/UpdateComponent"}}}},
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Component"}}},
					},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Component not found."},
				},
			},
			"delete": {
				"summary": "Delete a component",
				"tags": ["Components"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "pk", "in": "path", "required": True, "schema": {"type": "integer"}}],
				"responses": {
					"200": {"description": "Deleted."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Component not found."},
				},
			},
		},
		"/tracking/api/labels/": {
			"get": {
				"summary": "List labels for a project",
				"tags": ["Labels"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "project", "in": "query", "required": True, "schema": {"type": "string"}, "description": "Project key."}],
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/LabelList"}}},
					},
					"400": {"description": "Query parameter 'project' is required."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
				},
			},
			"post": {
				"summary": "Create a label in a project",
				"tags": ["Labels"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "project", "in": "query", "required": True, "schema": {"type": "string"}, "description": "Project key."}],
				"requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CreateLabel"}}}},
				"responses": {
					"201": {
						"description": "Created",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Label"}}},
					},
					"400": {"description": "Name is required."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"409": {"description": "Label already exists."},
				},
			},
		},
		"/tracking/api/attachments/": {
			"get": {
				"summary": "List attachments on a ticket",
				"tags": ["Attachments"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "ticket", "in": "query", "required": True, "schema": {"type": "integer"}, "description": "Ticket primary key."}],
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/AttachmentList"}}},
					},
					"400": {"description": "Query parameter 'ticket' is required."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
				},
			},
			"post": {
				"summary": "Upload an attachment (multipart/form-data)",
				"description": "Allowed file extensions: ``.png .jpg .jpeg .pdf .txt .log .json``. 10 MB cap enforced by the model.",
				"tags": ["Attachments"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "ticket", "in": "query", "required": True, "schema": {"type": "integer"}, "description": "Ticket primary key."}],
				"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {"$ref": "#/components/schemas/UploadAttachment"}}}},
				"responses": {
					"201": {
						"description": "Created",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Attachment"}}},
					},
					"400": {"description": "File is required or type not allowed."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
				},
			},
		},
		"/tracking/api/attachments/{pk}/": {
			"get": {
				"summary": "Retrieve an attachment metadata",
				"tags": ["Attachments"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "pk", "in": "path", "required": True, "schema": {"type": "integer"}}],
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Attachment"}}},
					},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Attachment not found."},
				},
			},
			"delete": {
				"summary": "Delete an attachment",
				"tags": ["Attachments"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "pk", "in": "path", "required": True, "schema": {"type": "integer"}}],
				"responses": {
					"200": {"description": "Deleted."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
				},
			},
		},
		"/tracking/api/sprints/{project_key}/": {
			"get": {
				"summary": "List sprints for a project",
				"tags": ["Sprints"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "project_key", "in": "path", "required": True, "schema": {"type": "string"}, "description": "Project key."}],
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/SprintList"}}},
					},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Project not found."},
				},
			},
		},
		"/tracking/api/sprints/{project_key}/active/tickets/": {
			"get": {
				"summary": "Tickets in the project's active sprint",
				"description": "When no sprint is active returns ``sprint: null`` and an empty ``tickets`` list.",
				"tags": ["Sprints"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "project_key", "in": "path", "required": True, "schema": {"type": "string"}, "description": "Project key."}],
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ActiveSprintTickets"}}},
					},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Project not found."},
				},
			},
		},
		"/tracking/api/sprints/{project_key}/create/": {
			"post": {
				"summary": "Create a sprint in a project",
				"tags": ["Sprints"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "project_key", "in": "path", "required": True, "schema": {"type": "string"}, "description": "Project key."}],
				"requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CreateSprint"}}}},
				"responses": {
					"201": {
						"description": "Created",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Sprint"}}},
					},
					"400": {"description": "'name' is required."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Project not found."},
					"409": {"description": "Sprint already exists."},
				},
			},
		},
		"/tracking/api/sprints/{pk}/": {
			"get": {
				"summary": "Retrieve a sprint",
				"tags": ["Sprints"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "pk", "in": "path", "required": True, "schema": {"type": "integer"}}],
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Sprint"}}},
					},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Sprint not found."},
				},
			},
			"patch": {
				"summary": "Update a sprint",
				"tags": ["Sprints"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "pk", "in": "path", "required": True, "schema": {"type": "integer"}}],
				"requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/UpdateSprint"}}}},
				"responses": {
					"200": {
						"description": "OK",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Sprint"}}},
					},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Sprint not found."},
				},
			},
			"delete": {
				"summary": "Delete a sprint (backlog is protected)",
				"tags": ["Sprints"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "pk", "in": "path", "required": True, "schema": {"type": "integer"}}],
				"responses": {
					"200": {"description": "Deleted."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"403": {"description": "Cannot delete the backlog pseudo-sprint."},
					"404": {"description": "Sprint not found."},
				},
			},
		},
		"/tracking/api/sprints/{project_key}/{sprint_pk}/close/": {
			"post": {
				"summary": "Close a sprint",
				"description": "Deactivates the sprint (sets ``is_active=False`` and ``end_date=today``). Action determines where open tickets go.",
				"tags": ["Sprints"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [
					{"name": "project_key", "in": "path", "required": True, "schema": {"type": "string"}, "description": "Project key."},
					{"name": "sprint_pk", "in": "path", "required": True, "schema": {"type": "integer"}, "description": "Sprint to close."},
				],
				"requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CloseSprint"}}}},
				"responses": {
					"200": {
						"description": "OK — sprint with updated dates.",
						"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Sprint"}}},
					},
					"400": {"description": "Invalid action or missing 'target_sprint'."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"403": {"description": "Cannot close the backlog pseudo-sprint."},
					"404": {"description": "Sprint not found."},
				},
			},
		},
		"/tracking/api/tickets/relations/{pk}/delete/": {
			"delete": {
				"summary": "Delete a ticket relation",
				"tags": ["Tickets"],
				"security": [{"Bearer": []}, {"Cookie": []}],
				"parameters": [{"name": "pk", "in": "path", "required": True, "schema": {"type": "integer"}, "description": "Relation primary key."}],
				"responses": {
					"200": {"description": "Deleted."},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"description": "Relation not found."},
				},
			},
		},
	}

	groups = [
		("Discovery", "Integration dataset: enums, types, transitions."),
		("Projects", "CRUD for projects."),
		("Tickets", "Ticket CRUD, state transitions, relations, comments, and attachments."),
		("Component", "Per-project components."),
		("Labels", "Per-project labels."),
		("Sprints", "Per-project sprints, active sprint tickets, and sprint close operations."),
	]

	return {
		"openapi": "3.1.0",
		"info": {
			"title": "SmartTracking REST API",
			"description": "Plain-Django JSON API for managing projects, tickets, sprints, comments, and attachments. "
			"Intended for programmatic / MCP client consumption. "
			"State changes must go through the **/transition/** endpoint.",
			"version": "0.1.0",
		},
		"servers": [
			{"url": "/tracking/api", "description": "API root (relative to Django site)."
			},
		],
		"paths": paths,
		"components": {
			"schemas": {
				"Meta": {
					"type": "object",
					"properties": {
						"types": {"type": "array", "items": {"$ref": "#/components/schemas/EnumEntry"}},
						"states": {"type": "array", "items": {"$ref": "#/components/schemas/EnumEntry"}},
						"priorities": {"type": "array", "items": {"$ref": "#/components/schemas/EnumEntry"}},
						"relations": {"type": "array", "items": {"$ref": "#/components/schemas/EnumEntry"}},
						"transitions": {
							"type": "object",
							"additionalProperties": {"type": "array", "items": {"type": "string"}},
							"description": "Map of state → list of reachable states.",
						},
					},
				},
				"EnumEntry": {
					"type": "object",
					"properties": {
						"value": {"type": "string"},
						"label": {"type": "string"},
					},
				},
				"Project": {
					"type": "object",
					"properties": {
						"key": {"type": "string"},
						"name": {"type": "string"},
						"description": {"type": "string"},
						"created_at": {"type": "string", "format": "date-time"},
					},
				},
				"ProjectList": {
					"type": "object",
					"properties": {
						"projects": {"type": "array", "items": {"$ref": "#/components/schemas/Project"}},
					},
				},
				"CreateProject": {
					"type": "object",
					"required": ["key", "name"],
					"properties": {
						"key": {"type": "string", "description": "Uppercase key, e.g. 'SMT'."},
						"name": {"type": "string"},
						"description": {"type": "string"},
					},
				},
				"Ticket": {
					"type": "object",
					"properties": {
						"id": {"type": "integer"},
						"project": {"type": "string", "description": "Project key."},
						"title": {"type": "string"},
						"description": {"type": "string"},
						"type": {"type": "string"},
						"type_display": {"type": "string"},
						"state": {"type": "string"},
						"state_display": {"type": "string"},
						"priority": {"type": "integer"},
						"priority_display": {"type": "string"},
						"estimation": {"type": ["number", "null"]},
						"parent_epic": {"type": ["integer", "null"]},
						"parent_epic_display": {"type": ["string", "null"]},
						"reporter": {"type": ["string", "null"]},
						"assignee": {"type": ["string", "null"]},
						"components": {"type": "array", "items": {"$ref": "#/components/schemas/Component"}},
						"labels": {"type": "array", "items": {"$ref": "#/components/schemas/Label"}},
						"relations": {"type": "array", "items": {"$ref": "#/components/schemas/TicketRelation"}},
						"allowed_transitions": {"type": "array", "items": {"type": "string"}},
						"comments": {"type": "array", "items": {"$ref": "#/components/schemas/Comment"}},
						"due_date": {"type": ["string", "null"], "format": "date"},
						"created_at": {"type": "string", "format": "date-time"},
						"updated_at": {"type": "string", "format": "date-time"},
					},
				},
				"TicketList": {
					"type": "object",
					"properties": {
						"tickets": {"type": "array", "items": {"$ref": "#/components/schemas/Ticket"}},
					},
				},
				"CreateTicket": {
					"type": "object",
					"required": ["project", "title"],
					"properties": {
						"project": {"type": "string"},
						"title": {"type": "string"},
						"description": {"type": "string"},
						"type": {"type": "string"},
						"priority": {"type": "integer"},
						"estimation": {"type": ["number", "null"]},
						"due_date": {"type": ["string", "null"], "format": "date"},
						"components": {"type": "array", "items": {"type": "string"}},
						"labels": {"type": "array", "items": {"type": "string"}},
					},
				},
				"UpdateTicket": {
					"type": "object",
					"properties": {
						"title": {"type": "string"},
						"description": {"type": "string"},
						"type": {"type": "string"},
						"estimation": {"type": ["number", "null"]},
						"priority": {"type": "integer"},
						"assignee": {"type": ["string", "null"]},
						"parent_epic": {"type": ["integer", "null"]},
						"due_date": {"type": ["string", "null"], "format": "date"},
						"sprint": {"type": ["integer", "null"]},
						"components": {"type": "array", "items": {"type": "string"}},
						"labels": {"type": "array", "items": {"type": "string"}},
					},
				},
				"TransitionTicket": {
					"type": "object",
					"required": ["state"],
					"properties": {"state": {"type": "string"}},
				},
				"TicketRelation": {
					"type": "object",
					"properties": {
						"id": {"type": "integer"},
						"subject": {"type": "integer"},
						"target": {"type": "integer"},
						"relation_type": {"type": "string"},
						"relation_type_display": {"type": "string"},
						"created_at": {"type": "string", "format": "date-time"},
					},
				},
				"CreateRelation": {
					"type": "object",
					"required": ["target_id", "relation_type"],
					"properties": {
						"target_id": {"type": "integer"},
						"relation_type": {"type": "string"},
					},
				},
				"Comment": {
					"type": "object",
					"properties": {
						"id": {"type": "integer"},
						"ticket": {"type": "integer"},
						"body": {"type": "string"},
						"author": {"type": ["string", "null"]},
						"created_at": {"type": "string", "format": "date-time"},
						"updated_at": {"type": "string", "format": "date-time"},
					},
				},
				"CommentList": {
					"type": "object",
					"properties": {"comments": {"type": "array", "items": {"$ref": "#/components/schemas/Comment"}}},
				},
				"CreateComment": {
					"type": "object",
					"required": ["body"],
					"properties": {"body": {"type": "string"}},
				},
				"Component": {
					"type": "object",
					"properties": {
						"id": {"type": "integer"},
						"project": {"type": "string"},
						"name": {"type": "string"},
						"description": {"type": "string"},
						"created_at": {"type": "string", "format": "date-time"},
					},
				},
				"ComponentList": {
					"type": "object",
					"properties": {"components": {"type": "array", "items": {"$ref": "#/components/schemas/Component"}}},
				},
				"CreateComponent": {
					"type": "object",
					"required": ["name"],
					"properties": {
						"name": {"type": "string"},
						"description": {"type": "string"},
					},
				},
				"UpdateComponent": {
					"type": "object",
					"properties": {
						"name": {"type": "string"},
						"description": {"type": "string"},
					},
				},
				"Label": {
					"type": "object",
					"properties": {
						"id": {"type": "integer"},
						"project": {"type": "string"},
						"name": {"type": "string"},
						"color": {"type": "string"},
						"description": {"type": "string"},
						"created_at": {"type": "string", "format": "date-time"},
					},
				},
				"LabelList": {
					"type": "object",
					"properties": {"labels": {"type": "array", "items": {"$ref": "#/components/schemas/Label"}}},
				},
				"CreateLabel": {
					"type": "object",
					"required": ["name"],
					"properties": {
						"name": {"type": "string"},
						"color": {"type": "string"},
						"description": {"type": "string"},
					},
				},
				"Attachment": {
					"type": "object",
					"properties": {
						"id": {"type": "integer"},
						"ticket": {"type": "integer"},
						"name": {"type": "string"},
						"mime_type": {"type": "string"},
						"url": {"type": "string"},
						"created_at": {"type": "string", "format": "date-time"},
					},
				},
				"AttachmentList": {
					"type": "object",
					"properties": {"attachments": {"type": "array", "items": {"$ref": "#/components/schemas/Attachment"}}},
				},
				"UploadAttachment": {
					"type": "object",
					"properties": {
						"file": {"type": "string", "format": "binary"},
					},
				},
				"Sprint": {
					"type": "object",
					"properties": {
						"id": {"type": "integer"},
						"project": {"type": "string"},
						"name": {"type": "string"},
						"description": {"type": "string"},
						"start_date": {"type": ["string", "null"], "format": "date"},
						"end_date": {"type": ["string", "null"], "format": "date"},
						"order": {"type": "integer"},
						"is_active": {"type": "boolean"},
						"created_at": {"type": "string", "format": "date-time"},
					},
				},
				"SprintList": {
					"type": "object",
					"properties": {"sprints": {"type": "array", "items": {"$ref": "#/components/schemas/Sprint"}}},
				},
				"CreateSprint": {
					"type": "object",
					"required": ["name"],
					"properties": {
						"name": {"type": "string"},
						"description": {"type": "string"},
						"start_date": {"type": ["string", "null"], "format": "date"},
						"end_date": {"type": ["string", "null"], "format": "date"},
						"order": {"type": "integer"},
						"is_active": {"type": "boolean"},
					},
				},
				"UpdateSprint": {
					"type": "object",
					"properties": {
						"name": {"type": "string"},
						"description": {"type": "string"},
						"start_date": {"type": ["string", "null"], "format": "date"},
						"end_date": {"type": ["string", "null"], "format": "date"},
						"order": {"type": "integer"},
						"is_active": {"type": "boolean"},
					},
				},
				"CloseSprint": {
					"type": "object",
					"properties": {
						"action": {"type": "string", "enum": ["backlog", "sprint", "keep"]},
						"target_sprint": {"type": ["integer", "null"]},
					},
				},
				"ActiveSprintTickets": {
					"type": "object",
					"properties": {
						"sprint": {"$ref": "#/components/schemas/Sprint"},
						"tickets": {"type": "array", "items": {"$ref": "#/components/schemas/Ticket"}},
					},
					"description": "``sprint`` is null when no sprint is active.",
				},
			},
			"responses": {
				"Unauthorized": {"description": "Authentication required. Check session cookie or ``Authorization: Bearer`` header."},
			},
			"securitySchemes": {
				"Bearer": {"type": "http", "scheme": "bearer"},
				"Cookie": {"type": "apiKey", "in": "cookie", "name": "sessionid"},
			},
		},
		"tags": [
			{"name": name, "description": desc} for name, desc in groups
		],
	}


@require_api_auth
@require_http_methods(["GET"])
def schema(request: HttpRequest) -> JsonResponse:
	"""Return the OpenAPI 3.1.0 spec as JSON.

	Load the document in any OpenAPI viewer (e.g. Swagger UI / ReDoc) by pointing
	it at ``/tracking/api/schema/``.
	"""
	return JsonResponse(_schema(), safe=False)


# --- URL patterns (included from tracking/urls.py) -------------------------

urlpatterns: list[path] = [
	path("meta/", meta, name="api_meta"),
	path("projects/", project_collection, name="api_project_collection"),
	path("projects/<str:key>/", project_detail, name="api_project_detail"),
	path("tickets/", ticket_collection, name="api_ticket_collection"),
	path("tickets/<int:pk>/", ticket_detail, name="api_ticket_detail"),
	path("tickets/<int:pk>/transition/", ticket_transition, name="api_ticket_transition"),
	path("tickets/<int:pk>/relations/add/", ticket_relation_create, name="api_ticket_relation_create"),
	path("comments/", comment_collection, name="api_comment_collection"),
	path("components/", component_collection, name="api_component_collection"),
	path("components/<int:pk>/", component_detail, name="api_component_detail"),
	path("labels/", label_collection, name="api_label_collection"),
	path("attachments/", attachment_collection, name="api_attachment_collection"),
	path("attachments/<int:pk>/", attachment_detail, name="api_attachment_detail"),
	path("sprints/<str:project_key>/", sprint_collection, name="api_sprint_collection"),
	path("sprints/<str:project_key>/active/tickets/", active_sprint_tickets, name="api_active_sprint_tickets"),
	path("sprints/<str:project_key>/create/", sprint_create, name="api_sprint_create"),
	path("sprints/<str:project_key>/<int:sprint_pk>/close/", sprint_close, name="api_sprint_close"),
	path("sprints/<int:pk>/", sprint_detail, name="api_sprint_detail"),
	path("tickets/relations/<int:pk>/delete/", ticket_relation_delete_api, name="api_ticket_relation_delete"),
	path("schema/", schema, name="api_schema"),
]
