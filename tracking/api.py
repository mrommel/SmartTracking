"""Lightweight JSON REST API for the tracking app.

Built with plain Django (no DRF) to stay dependency-free and consistent with
the rest of the project. Intended to be consumed programmatically — e.g. by an
MCP server that exposes tickets/projects as tools to an AI agent.

All endpoints speak JSON and are CSRF-exempt (they are not browser-form driven).
The state machine is *not* re-implemented here: state changes go through
``Ticket.can_transition_to`` exactly like the HTML views do.

Routes are wired in ``tracking/urls.py`` under ``/tracking/api/``.
"""

import hmac
import json
from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Attachment, Comment, Component, Label, Project, Ticket


# --- Authentication --------------------------------------------------------

def _token_ok(request):
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


def require_api_auth(view):
	"""Allow either a logged-in session or a valid API token.

	MCP clients authenticate with ``Authorization: Bearer <TRACKING_API_TOKEN>``
	(or an ``X-API-Token`` header); browser sessions work too for convenience.
	"""

	@wraps(view)
	def wrapper(request, *args, **kwargs):
		if request.user.is_authenticated or _token_ok(request):
			return view(request, *args, **kwargs)
		response = JsonResponse({"error": "Authentication required."}, status=401)
		response["WWW-Authenticate"] = "Bearer"
		return response

	return wrapper


# --- Serialization helpers -------------------------------------------------

def serialize_project(project):
	return {
		"key": project.key,
		"name": project.name,
		"description": project.description,
		"created_at": project.created_at.isoformat(),
	}


def serialize_ticket(ticket):
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
		"reporter": str(ticket.reporter) if ticket.reporter else None,
		"assignee": str(ticket.assignee) if ticket.assignee else None,
		"components": [
			serialize_component(c) for c in ticket.components.all()
		],
		"labels": [
			serialize_label(l) for l in ticket.labels.all()
		],
		"allowed_transitions": [s.value for s in ticket.allowed_transitions()],
		"comments": [
			serialize_comment(c)
			for c in ticket.comments.select_related("author").all()
		],
		"created_at": ticket.created_at.isoformat(),
		"updated_at": ticket.updated_at.isoformat(),
	}


def serialize_comment(comment):
	return {
		"id": comment.pk,
		"ticket": comment.ticket.pk,
		"body": comment.body,
		"author": str(comment.author) if comment.author else None,
		"created_at": comment.created_at.isoformat(),
		"updated_at": comment.updated_at.isoformat(),
	}


def serialize_component(component):
	return {
		"id": component.pk,
		"project": component.project.key,
		"name": component.name,
		"description": component.description,
		"created_at": component.created_at.isoformat(),
	}


def serialize_label(label):
	return {
		"id": label.pk,
		"project": label.project.key,
		"name": label.name,
		"color": label.color,
		"description": label.description,
		"created_at": label.created_at.isoformat(),
	}


def serialize_attachment(attachment):
	from django.conf import settings
	return {
		"id": attachment.pk,
		"ticket": attachment.ticket.pk,
		"name": attachment.name,
		"mime_type": attachment.mime_type,
		"url": f"{settings.MEDIA_URL}attachments/{attachment.ticket.project.key}/{attachment.ticket.pk}/{attachment.file_extension}/{attachment.name}",
		"created_at": attachment.created_at.isoformat(),
	}


def _parse_json(request):
	"""Return the parsed JSON body, or raise ``ValueError`` on bad input."""
	if not request.body:
		return {}
	return json.loads(request.body)


def _error(message, status=400, **extra):
	return JsonResponse({"error": message, **extra}, status=status)


# --- Meta / discovery ------------------------------------------------------

@require_api_auth
@require_http_methods(["GET"])
def meta(request):
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
		"transitions": {
			state.value: [s.value for s in targets]
			for state, targets in Ticket.TRANSITIONS.items()
		},
	})


# --- Projects --------------------------------------------------------------

@csrf_exempt
@require_api_auth
@require_http_methods(["GET", "POST"])
def project_collection(request):
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
def project_detail(request, key):
	project = get_object_or_404(Project, key=key.upper())
	return JsonResponse(serialize_project(project))


# --- Tickets ---------------------------------------------------------------

@csrf_exempt
@require_api_auth
@require_http_methods(["GET", "POST"])
def ticket_collection(request):
	if request.method == "GET":
		tickets = Ticket.objects.select_related("project", "assignee", "reporter")
		project_key = request.GET.get("project")
		if project_key:
			tickets = tickets.filter(project__key=project_key.upper())
		state = request.GET.get("state")
		if state:
			tickets = tickets.filter(state=state)
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
	)
	if request.user.is_authenticated:
		ticket.reporter = request.user
	ticket.save()

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
def ticket_detail(request, pk):
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

	updatable = {"title", "description", "type", "priority"}
	changed = []
	for field in updatable & set(data):
		value = data[field]
		if field == "type" and value not in Ticket.Type.values:
			return _error(f"Invalid type '{value}'.")
		if field == "priority" and value not in Ticket.Priority.values:
			return _error(f"Invalid priority '{value}'.")
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
		ticket.save(update_fields=[*changed, "updated_at"])
	return JsonResponse(serialize_ticket(ticket))


@csrf_exempt
@require_api_auth
@require_http_methods(["POST"])
def ticket_transition(request, pk):
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

	ticket.state = new_state
	ticket.save(update_fields=["state", "updated_at"])
	return JsonResponse(serialize_ticket(ticket))


# --- Comments --------------------------------------------------------------

@csrf_exempt
@require_api_auth
@require_http_methods(["GET", "POST"])
def comment_collection(request):
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
	return JsonResponse(serialize_comment(comment), status=201)


# --- Components -------------------------------------------------------------

@csrf_exempt
@require_api_auth
@require_http_methods(["GET", "POST"])
def component_collection(request):
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
def component_detail(request, pk):
	"""Retrieve, update, or delete a single component."""
	component = get_object_or_404(Component, pk=pk)

	if request.method == "GET":
		return JsonResponse(serialize_component(component))

	if request.method == "PATCH":
		try:
			data = _parse_json(request)
		except (ValueError, json.JSONDecodeError):
			return _error("Request body must be valid JSON.")

		changed = []
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
def label_collection(request):
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
def attachment_collection(request):
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
	return JsonResponse(serialize_attachment(attachment), status=201)


@csrf_exempt
@require_api_auth
@require_http_methods(["GET", "DELETE"])
def attachment_detail(request, pk):
	attachment = get_object_or_404(Attachment, pk=pk)
	if request.method == "GET":
		return JsonResponse(serialize_attachment(attachment))
	# DELETE -> remove attachment
	attachment.file.delete()
	attachment.delete()
	return JsonResponse({"status": "deleted"})


# --- URL patterns (included from tracking/urls.py) -------------------------

urlpatterns = [
	path("meta/", meta, name="api_meta"),
	path("projects/", project_collection, name="api_project_collection"),
	path("projects/<str:key>/", project_detail, name="api_project_detail"),
	path("tickets/", ticket_collection, name="api_ticket_collection"),
	path("tickets/<int:pk>/", ticket_detail, name="api_ticket_detail"),
	path("tickets/<int:pk>/transition/", ticket_transition, name="api_ticket_transition"),
	path("comments/", comment_collection, name="api_comment_collection"),
	path("components/", component_collection, name="api_component_collection"),
	path("components/<int:pk>/", component_detail, name="api_component_detail"),
	path("labels/", label_collection, name="api_label_collection"),
	path("attachments/", attachment_collection, name="api_attachment_collection"),
	path("attachments/<int:pk>/", attachment_detail, name="api_attachment_detail"),
]
