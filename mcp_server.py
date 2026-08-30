"""SmartTracking MCP server.

Started automatically by ``make run`` (alongside the Django dev server) and
serves the Model Context Protocol over streamable HTTP, so an LLM agent in
another project can connect while SmartTracking is running.

Each MCP tool is a thin wrapper around a REST endpoint in ``tracking/api.py``;
all domain rules (enums, the state-transition graph, auth) stay enforced by the
Django API. Configuration comes from the environment (loaded from ``.env``):

    SMARTTRACKING_URL   base URL of the Django app   (default http://127.0.0.1:8092)
    TRACKING_API_TOKEN  bearer token for the REST API
    MCP_HOST / MCP_PORT where this MCP server listens (default 127.0.0.1:8091)
    TRACKING_HTTP_TIMEOUT  upstream request timeout in seconds (default 15)

Two transports are supported:

    python mcp_server.py            # streamable HTTP on MCP_HOST:MCP_PORT/mcp
    python mcp_server.py --stdio    # stdio, for clients that spawn a subprocess

The HTTP transport runs **stateless** (no ``Mcp-Session-Id``) with JSON
responses, so restarting this process can never strand a connected editor on a
dead session id. ``GET /health`` reports upstream reachability.
"""

import argparse
import difflib
import json
import logging
import os
import sys
import time
from typing import Any

import anyio
import anyio.to_thread
import httpx
import uvicorn
from mcp.server import Server
from mcp.types import (
	CallToolResult,
	ListToolsResult,
	TextContent,
	Tool,
)
from starlette.responses import JSONResponse
from starlette.routing import Route

# ── Logging setup ──────────────────────────────────────────────────────────
# The "Failed to validate request" errors are NOT emitted via Python's logging
# module (likely from a compiled extension or the client side).  We add a
# stderr-based logger so we can see every request/response cycle and correlate
# timestamps with the validation errors.

_console = logging.StreamHandler(sys.stderr)
_console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_logger = logging.getLogger("smarttracking.mcp")
_logger.setLevel(logging.DEBUG)
_logger.addHandler(_console)

# Also suppress noisy Pydantic validation warnings from the MCP library's
# request router.  These fire on every request as the router tries all 21+
# message types before dispatching to the correct handler — they are harmless
# but spam the console.
logging.getLogger("pydantic").setLevel(logging.ERROR)
logging.getLogger("mcp.server.streamable_http").setLevel(logging.ERROR)

BASE_URL = os.environ.get("SMARTTRACKING_URL", "http://127.0.0.1:8092").rstrip("/")
API = f"{BASE_URL}/tracking/api"
TOKEN = os.environ.get("TRACKING_API_TOKEN", "")

MCP_HOST = os.environ.get("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("MCP_PORT", "8091"))

# Upstream (Django REST API) request timeout in seconds.  Kept low so a stalled
# Django worker can never hold an MCP tool call open long enough for the client
# to give up on the whole session.
HTTP_TIMEOUT = float(os.environ.get("TRACKING_HTTP_TIMEOUT", "15"))

# MCP requires `inputSchema` to be a JSON-Schema *object*.  A bare ``{}`` is
# rejected by strict clients (opencode / Zod) while they validate the
# `tools/list` result, which aborts the whole session before the first tool
# call.  Zero-argument tools must therefore advertise this instead.
NO_ARGS_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


def _client() -> httpx.Client:
	headers = {"Accept": "application/json"}
	if TOKEN:
		headers["Authorization"] = f"Bearer {TOKEN}"
	return httpx.Client(base_url=API, headers=headers, timeout=HTTP_TIMEOUT)


# A stopped/restarting Django dev server refuses connections for a moment.
# Retry idempotent-looking transport failures a couple of times before giving
# up, then report a readable error instead of an httpx traceback.
_TRANSPORT_RETRIES = 2
_TRANSPORT_RETRY_DELAY = 0.5


def _request(method: str, path: str, **kwargs: Any) -> Any:
	"""Call the REST API and return parsed JSON, surfacing errors to the agent."""
	_logger.debug("API %s %s %s", method, path, kwargs.get("json", kwargs.get("params", {})))
	last_exc: httpx.HTTPError | None = None
	resp = None
	for attempt in range(_TRANSPORT_RETRIES + 1):
		try:
			with _client() as client:
				resp = client.request(method, path, **kwargs)
			break
		except httpx.HTTPError as exc:
			last_exc = exc
			_logger.warning(
				"API %s %s transport error (attempt %d/%d): %s",
				method, path, attempt + 1, _TRANSPORT_RETRIES + 1, exc,
			)
			if attempt < _TRANSPORT_RETRIES:
				time.sleep(_TRANSPORT_RETRY_DELAY)
	if resp is None:
		return _upstream_unreachable(method, path, last_exc)
	try:
		body = resp.json()
	except ValueError:
		body = {"error": resp.text}
	if resp.status_code >= 400:
		_logger.debug("API %s %s -> %d", method, path, resp.status_code)
		return {"status": resp.status_code, **body}
	_logger.debug("API %s %s -> %d", method, path, resp.status_code)
	return body


def _upstream_unreachable(method: str, path: str, exc: httpx.HTTPError | None) -> dict[str, Any]:
	"""Return a structured, actionable error for a failed upstream connection."""
	reason = f"{type(exc).__name__}: {exc}" if exc is not None else "unknown transport error"
	_logger.error("API %s %s unreachable: %s", method, path, reason)
	kind = "timeout" if isinstance(exc, httpx.TimeoutException) else "connection"
	return {
		"status": 503,
		"error": f"SmartTracking API at {BASE_URL} is unreachable ({kind} error).",
		"detail": reason,
		"hint": (
			"The Django app is not running (or SMARTTRACKING_URL points elsewhere). "
			"Start it with `make run` in the SmartTracking project, then retry."
		),
	}


# ── Tool definitions ───────────────────────────────────────────────────────

TOOLS: list[Tool] = [
	Tool(
		name="get_meta",
		description="Return ticket enums (types, states, priorities) and the state-transition graph. Call this first to learn valid values before creating/moving tickets.",
		inputSchema=NO_ARGS_SCHEMA,
	),
	Tool(
		name="list_projects",
		description="List all projects.",
		inputSchema=NO_ARGS_SCHEMA,
	),
	Tool(
		name="get_project",
		description="Get a single project by its uppercase key (e.g. 'SMT').",
		inputSchema={"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
	),
	Tool(
		name="create_project",
		description="Create a project. `key` is a short uppercase identifier used as the ticket-ID prefix (e.g. 'SMT'). Returns status 409 if the key already exists.",
		inputSchema={
			"type": "object",
			"properties": {
				"key": {"type": "string"},
				"name": {"type": "string"},
				"description": {"type": "string"},
			},
			"required": ["key", "name"],
		},
	),
	Tool(
		name="list_tickets",
		description="List tickets, optionally filtered by project key and/or state value. Paginated: pass `page` (1-based) and `page_size` (default 25, max 100) to page through large projects instead of pulling everything at once.",
		inputSchema={
			"type": "object",
			"properties": {
				"project": {"type": "string"},
				"state": {"type": "string"},
				"page": {"type": "integer"},
				"page_size": {"type": "integer"},
			},
		},
	),
	Tool(
		name="get_ticket",
		description="Get a single ticket by numeric id. The response includes `allowed_transitions` for the current state.",
		inputSchema={"type": "object", "properties": {"ticket_id": {"type": "integer"}}, "required": ["ticket_id"]},
	),
	Tool(
		name="create_ticket",
		description="Create a ticket in a project. `type` is one of task/bug/story/epic; `priority` is 1..4 (low..critical). `estimation` is an optional integer. See `get_meta` for exact values.",
		inputSchema={
			"type": "object",
			"properties": {
				"project": {"type": "string"},
				"title": {"type": "string"},
				"type": {"type": "string"},
				"priority": {"type": "integer"},
				"estimation": {"type": "integer"},
				"description": {"type": "string"},
			},
			"required": ["project", "title"],
		},
	),
	Tool(
		name="update_ticket",
		description="Partially update a ticket's fields. To change the state, use `transition_ticket` instead (this endpoint rejects a 'state' key). `labels` and `components` accept a list of label/component names for the project; unknown names are silently ignored. `sprint` accepts a sprint pk to assign the ticket to a specific sprint.",
		inputSchema={
			"type": "object",
			"properties": {
				"ticket_id": {"type": "integer"},
				"title": {"type": "string"},
				"description": {"type": "string"},
				"type": {"type": "string"},
				"estimation": {"type": "integer"},
				"priority": {"type": "integer"},
				"labels": {"type": "array", "items": {"type": "string"}},
				"components": {"type": "array", "items": {"type": "string"}},
				"sprint": {"type": "integer"},
			},
			"required": ["ticket_id"],
		},
	),
	Tool(
		name="transition_ticket",
		description="Move a ticket to a new state, honouring the transition graph. On an illegal move returns status 409 with the list of `allowed_transitions`.",
		inputSchema={
			"type": "object",
			"properties": {
				"ticket_id": {"type": "integer"},
				"state": {"type": "string"},
			},
			"required": ["ticket_id", "state"],
		},
	),
	Tool(
		name="list_labels",
		description="List all labels defined for a project. Use this to learn valid label names before setting them on a ticket via `update_ticket`.",
		inputSchema={"type": "object", "properties": {"project": {"type": "string"}}, "required": ["project"]},
	),
	Tool(
		name="list_components",
		description="List all components defined for a project. Use this to learn valid component names before setting them on a ticket via `update_ticket`.",
		inputSchema={"type": "object", "properties": {"project": {"type": "string"}}, "required": ["project"]},
	),
	Tool(
		name="create_component",
		description="Create a component for a project. Returns status 409 if the name already exists in that project.",
		inputSchema={
			"type": "object",
			"properties": {
				"project": {"type": "string"},
				"name": {"type": "string"},
				"description": {"type": "string"},
			},
			"required": ["project", "name"],
		},
	),
	Tool(
		name="update_component",
		description="Partially update a component's fields. Any field not provided is left unchanged. Returns 404 if the component does not exist.",
		inputSchema={
			"type": "object",
			"properties": {
				"component_id": {"type": "integer"},
				"name": {"type": "string"},
				"description": {"type": "string"},
			},
			"required": ["component_id"],
		},
	),
	Tool(
		name="delete_component",
		description="Delete a component. Returns status 404 if not found.",
		inputSchema={"type": "object", "properties": {"component_id": {"type": "integer"}}, "required": ["component_id"]},
	),
	Tool(
		name="create_label",
		description="Create a label for a project. Returns status 409 if the name already exists in that project.",
		inputSchema={
			"type": "object",
			"properties": {
				"project": {"type": "string"},
				"name": {"type": "string"},
				"color": {"type": "string"},
				"description": {"type": "string"},
			},
			"required": ["project", "name"],
		},
	),
	Tool(
		name="list_attachments",
		description="List all attachments for a ticket.",
		inputSchema={"type": "object", "properties": {"ticket_id": {"type": "integer"}}, "required": ["ticket_id"]},
	),
	Tool(
		name="get_attachment",
		description="Get a single attachment by numeric id.",
		inputSchema={"type": "object", "properties": {"attachment_id": {"type": "integer"}}, "required": ["attachment_id"]},
	),
	Tool(
		name="delete_attachment",
		description="Delete an attachment. Returns status 404 if not found.",
		inputSchema={"type": "object", "properties": {"attachment_id": {"type": "integer"}}, "required": ["attachment_id"]},
	),
	Tool(
		name="upload_attachment",
		description="Upload a file to a ticket. The file must exist on the local filesystem. Allowed extensions: png, jpg, jpeg, pdf, txt, log, json.",
		inputSchema={
			"type": "object",
			"properties": {
				"ticket_id": {"type": "integer"},
				"file_path": {"type": "string"},
			},
			"required": ["ticket_id", "file_path"],
		},
	),
	Tool(
		name="list_sprints",
		description="List all sprints for a project. Returns list of sprints with their ids, names, dates, and active status.",
		inputSchema={"type": "object", "properties": {"project_key": {"type": "string"}}, "required": ["project_key"]},
	),
	Tool(
		name="get_active_sprint_tickets",
		description="Return the tickets of the project's active sprint. A project has at most one active sprint; when none is active, returns `sprint: null` and an empty `tickets` list.",
		inputSchema={"type": "object", "properties": {"project_key": {"type": "string"}}, "required": ["project_key"]},
	),
	Tool(
		name="create_sprint",
		description="Create a sprint in a project. Returns status 409 if the name already exists in that project. `order` controls display order; `is_active` makes this the current active sprint (deactivating any other active sprint in the same project).",
		inputSchema={
			"type": "object",
			"properties": {
				"project_key": {"type": "string"},
				"name": {"type": "string"},
				"description": {"type": "string"},
				"start_date": {"type": "string"},
				"end_date": {"type": "string"},
				"order": {"type": "integer"},
				"is_active": {"type": "boolean"},
			},
			"required": ["project_key", "name"],
		},
	),
	Tool(
		name="update_sprint",
		description="Partially update a sprint's fields. Any field not provided is left unchanged. Returns 404 if the sprint does not exist. Setting `is_active=True` deactivates any other active sprint in the same project.",
		inputSchema={
			"type": "object",
			"properties": {
				"sprint_id": {"type": "integer"},
				"name": {"type": "string"},
				"description": {"type": "string"},
				"start_date": {"type": "string"},
				"end_date": {"type": "string"},
				"order": {"type": "integer"},
				"is_active": {"type": "boolean"},
			},
			"required": ["sprint_id"],
		},
	),
	Tool(
		name="delete_sprint",
		description="Delete a sprint. Cannot delete the backlog pseudo-sprint (pk=1). Returns status 403 if deletion is not allowed.",
		inputSchema={"type": "object", "properties": {"sprint_id": {"type": "integer"}}, "required": ["sprint_id"]},
	),
	Tool(
		name="close_sprint",
		description="Close an active sprint (deactivate it and set end_date to today). `action` controls what happens to unassigned tickets: 'backlog' (default) moves them to backlog (sprint=None), 'sprint' moves them to another sprint (requires `target_sprint`), 'keep' leaves tickets as-is. Returns status 403 if the sprint is the backlog pseudo-sprint, or 404 if not found.",
		inputSchema={
			"type": "object",
			"properties": {
				"project_key": {"type": "string"},
				"sprint_id": {"type": "integer"},
				"action": {"type": "string"},
				"target_sprint": {"type": "integer"},
			},
			"required": ["project_key", "sprint_id"],
		},
	),
	Tool(
		name="add_relation",
		description="Create a relation from one ticket to another within the same project. `relation_type` is one of: related_to, blocked_by, tested_with. Returns status 409 if the relation already exists or tickets are in different projects.",
		inputSchema={
			"type": "object",
			"properties": {
				"ticket_id": {"type": "integer"},
				"target_id": {"type": "integer"},
				"relation_type": {"type": "string"},
			},
			"required": ["ticket_id", "target_id", "relation_type"],
		},
	),
	Tool(
		name="delete_relation",
		description="Delete a ticket relation. Returns status 404 if not found. Note: this endpoint has a known bug and currently raises an AttributeError when deleting relations with inverse types (blocked_by, tested_with).",
		inputSchema={"type": "object", "properties": {"relation_id": {"type": "integer"}}, "required": ["relation_id"]},
	),
]


class MissingArgumentError(Exception):
	"""Raised when a required tool argument is absent or uncastable."""

	def __init__(self, name: str, detail: str):
		super().__init__(detail)
		self.name = name
		self.detail = detail


def _get_arg(args: dict, name: str, default: Any = None):
	"""Get an argument from the tool call arguments, converting to int if needed."""
	if name not in args:
		return default
	val = args[name]
	if isinstance(default, int) and isinstance(val, str):
		return int(val)
	if isinstance(default, bool) and isinstance(val, str):
		return val.lower() in ("true", "1", "yes")
	return val


def _require(args: dict, name: str, cast: type = str):
	"""Return a *required* argument, cast to ``cast``.

	Historically call sites passed the type itself as the ``default`` of
	``_get_arg`` (e.g. ``_get_arg(args, 'key', str)``).  When the argument was
	missing that returned the ``str`` *class*, which then interpolated into the
	URL as ``/projects/<class 'str'>/`` and produced a baffling 404 instead of a
	usable error.  This helper fails loudly and structurally instead.
	"""
	if name not in args or args[name] is None:
		raise MissingArgumentError(name, f"Missing required argument: '{name}'")
	val = args[name]
	try:
		if cast is int and not isinstance(val, int):
			return int(val)
		if cast is bool and not isinstance(val, bool):
			return str(val).lower() in ("true", "1", "yes")
		if cast is str and not isinstance(val, str):
			return str(val)
	except (TypeError, ValueError) as exc:
		raise MissingArgumentError(
			name, f"Argument '{name}' must be of type {cast.__name__}, got {val!r}"
		) from exc
	return val


def _paging(args: dict) -> dict:
	"""Extract the optional ``page`` / ``page_size`` pagination params."""
	params = {}
	for key in ("page", "page_size"):
		value = _get_arg(args, key)
		if value is not None:
			params[key] = int(value)
	return params


async def handle_list_tools(ctx: Any = None, params: Any = None) -> ListToolsResult:
	"""``tools/list`` handler.

	The low-level ``Server`` invokes registered handlers as
	``handler(ctx, params)`` — the signature is positional, so it is pinned here
	rather than swallowed by ``*args``.
	"""
	return ListToolsResult(tools=TOOLS)


async def handle_call_tool(ctx: Any = None, params: Any = None) -> CallToolResult:
	"""``tools/call`` handler.

	CRITICAL: the low-level ``Server`` calls this as ``handler(ctx, params)``
	where ``params`` is a ``CallToolRequestParams`` carrying ``.name`` and
	``.arguments``.  The previous signature was ``(name, arguments)``, so the
	*context object* was used as the tool name and every single call over the
	wire fell through to the ``Unknown tool`` branch — while the unit tests
	(which call the module-level wrappers directly) stayed green.
	"""
	name = getattr(params, "name", None)
	arguments = getattr(params, "arguments", None) or {}

	if not name:
		return _error_result("Malformed tools/call request: no tool name supplied.")

	# The upstream REST call is synchronous (httpx.Client).  Running it inline
	# would block the event loop for up to HTTP_TIMEOUT seconds, starving the
	# streamable-HTTP transport of keep-alives and causing clients to drop the
	# session.  Push it to a worker thread instead.
	try:
		result = await anyio.to_thread.run_sync(lambda: _call_tool_impl(name, arguments))
	except MissingArgumentError as exc:
		return _error_result(exc.detail)
	except Exception as exc:  # noqa: BLE001 - never kill the session on a tool error
		_logger.exception("Tool %s failed", name)
		return _error_result(f"{type(exc).__name__}: {exc}")

	return _to_result(result)


def _json_text(payload: Any) -> str:
	"""Serialise a tool result as JSON (never a Python ``repr``)."""
	try:
		return json.dumps(payload, indent=2, default=str)
	except (TypeError, ValueError):
		return json.dumps({"error": str(payload)})


def _to_result(payload: Any) -> CallToolResult:
	"""Wrap a tool payload, flagging upstream 4xx/5xx as an MCP tool error."""
	is_error = isinstance(payload, dict) and isinstance(payload.get("status"), int) and payload["status"] >= 400
	return CallToolResult(
		content=[TextContent(type="text", text=_json_text(payload))],
		is_error=is_error,
	)


def _error_result(message: str) -> CallToolResult:
	return CallToolResult(
		content=[TextContent(type="text", text=_json_text({"error": message}))],
		is_error=True,
	)


def _call_tool_impl(name: str, args: dict) -> Any:
	if name == "get_meta":
		return _request("GET", "/meta/")
	elif name == "list_projects":
		return _request("GET", "/projects/")
	elif name == "get_project":
		return _request("GET", f"/projects/{_require(args, 'key')}/")
	elif name == "create_project":
		return _request(
			"POST", "/projects/",
			json={"key": _require(args, "key"), "name": _require(args, "name"), "description": _get_arg(args, "description", "")},
		)
	elif name == "list_tickets":
		params = _paging(args)
		if project := _get_arg(args, "project"):
			params["project"] = project
		if state := _get_arg(args, "state"):
			params["state"] = state
		return _request("GET", "/tickets/", params=params)
	elif name == "get_ticket":
		return _request("GET", f"/tickets/{_require(args, 'ticket_id', int)}/")
	elif name == "create_ticket":
		return _request(
			"POST", "/tickets/",
			json={
				"project": _require(args, "project"),
				"title": _require(args, "title"),
				"type": _get_arg(args, "type", "task"),
				"priority": _get_arg(args, "priority", 2),
				"estimation": _get_arg(args, "estimation"),
				"description": _get_arg(args, "description", ""),
			},
		)
	elif name == "update_ticket":
		payload = {
			k: v
			for k, v in {
				"title": _get_arg(args, "title"),
				"description": _get_arg(args, "description"),
				"type": _get_arg(args, "type"),
				"estimation": _get_arg(args, "estimation"),
				"priority": _get_arg(args, "priority"),
				"labels": _get_arg(args, "labels"),
				"components": _get_arg(args, "components"),
				"sprint": _get_arg(args, "sprint"),
			}.items()
			if v is not None
		}
		return _request("PATCH", f"/tickets/{_require(args, 'ticket_id', int)}/", json=payload)
	elif name == "transition_ticket":
		return _request(
			"POST", f"/tickets/{_require(args, 'ticket_id', int)}/transition/",
			json={"state": _require(args, "state")},
		)
	elif name == "list_labels":
		return _request("GET", "/labels/", params={"project": _require(args, "project")})
	elif name == "list_components":
		return _request("GET", "/components/", params={"project": _require(args, "project")})
	elif name == "create_component":
		return _request(
			"POST", "/components/",
			json={"project": _require(args, "project"), "name": _require(args, "name"), "description": _get_arg(args, "description", "")},
		)
	elif name == "update_component":
		payload = {
			k: v
			for k, v in {"name": _get_arg(args, "name"), "description": _get_arg(args, "description")}.items()
			if v is not None
		}
		return _request("PATCH", f"/components/{_require(args, 'component_id', int)}/", json=payload)
	elif name == "delete_component":
		return _request("DELETE", f"/components/{_require(args, 'component_id', int)}/")
	elif name == "create_label":
		return _request(
			"POST", "/labels/",
			json={"project": _require(args, "project"), "name": _require(args, "name"), "color": _get_arg(args, "color", "secondary"), "description": _get_arg(args, "description", "")},
		)
	elif name == "list_attachments":
		return _request("GET", "/attachments/", params={"ticket": _require(args, "ticket_id", int)})
	elif name == "get_attachment":
		return _request("GET", f"/attachments/{_require(args, 'attachment_id', int)}/")
	elif name == "delete_attachment":
		return _request("DELETE", f"/attachments/{_require(args, 'attachment_id', int)}/")
	elif name == "upload_attachment":
		ticket_id = _require(args, "ticket_id", int)
		file_path = _require(args, "file_path")
		with _client() as client:
			try:
				with open(file_path, "rb") as f:
					resp = client.post(
						"/attachments/",
						files={"file": (os.path.basename(file_path), f)},
						params={"ticket": ticket_id},
					)
			except FileNotFoundError:
				return {"status": 400, "error": f"File not found: {file_path}"}
		try:
			body = resp.json()
		except ValueError:
			body = {"error": resp.text}
		return {"status": resp.status_code, **body}
	elif name == "list_sprints":
		return _request("GET", f"/sprints/{_require(args, 'project_key')}/")
	elif name == "get_active_sprint_tickets":
		return _request("GET", f"/sprints/{_require(args, 'project_key')}/active/tickets/")
	elif name == "create_sprint":
		return _request(
			"POST", f"/sprints/{_require(args, 'project_key')}/create/",
			json={
				"name": _require(args, "name"),
				"description": _get_arg(args, "description", ""),
				"start_date": _get_arg(args, "start_date"),
				"end_date": _get_arg(args, "end_date"),
				"order": _get_arg(args, "order", 0),
				"is_active": _get_arg(args, "is_active", False),
			},
		)
	elif name == "update_sprint":
		payload = {
			k: v
			for k, v in {
				"name": _get_arg(args, "name"),
				"description": _get_arg(args, "description"),
				"start_date": _get_arg(args, "start_date"),
				"end_date": _get_arg(args, "end_date"),
				"order": _get_arg(args, "order"),
				"is_active": _get_arg(args, "is_active"),
			}.items()
			if v is not None
		}
		return _request("PATCH", f"/sprints/{_require(args, 'sprint_id', int)}/", json=payload)
	elif name == "delete_sprint":
		return _request("DELETE", f"/sprints/{_require(args, 'sprint_id', int)}/")
	elif name == "close_sprint":
		return _request(
			"POST", f"/sprints/{_require(args, 'project_key')}/{_require(args, 'sprint_id', int)}/close/",
			json={"action": _get_arg(args, "action", "backlog"), "target_sprint": _get_arg(args, "target_sprint")},
		)
	elif name == "add_relation":
		return _request(
			"POST", f"/tickets/{_require(args, 'ticket_id', int)}/relations/add/",
			json={"target_id": _require(args, "target_id", int), "relation_type": _require(args, "relation_type")},
		)
	elif name == "delete_relation":
		return _request("DELETE", f"/tickets/relations/{_require(args, 'relation_id', int)}/delete/")
	else:
		# Surface a suggestion so a model that hallucinated a near-miss name can
		# self-correct on the next turn instead of retrying the same bad call.
		known = [t.name for t in TOOLS]
		hint = difflib.get_close_matches(str(name), known, n=3, cutoff=0.5)
		return {
			"status": 400,
			"error": f"Unknown tool: {name}",
			"did_you_mean": hint,
			"available_tools": known,
		}


mcp = Server(
	"smarttracking",
	on_list_tools=handle_list_tools,
	on_call_tool=handle_call_tool,
)


# ── Module-level tool functions for testability ────────────────────────────
# The MCP server's test suite calls these directly (patching _request).
# Each is a thin wrapper around _call_tool_impl so both the MCP handler and
# the tests share the same logic.

def get_meta():
	return _call_tool_impl("get_meta", {})

def list_projects():
	return _call_tool_impl("list_projects", {})

def get_project(key):
	return _call_tool_impl("get_project", {"key": key})

def create_project(key, name, description=""):
	return _call_tool_impl("create_project", {"key": key, "name": name, "description": description})

def list_tickets(project=None, state=None, page=None, page_size=None):
	args = {}
	if project:
		args["project"] = project
	if state:
		args["state"] = state
	if page is not None:
		args["page"] = page
	if page_size is not None:
		args["page_size"] = page_size
	return _call_tool_impl("list_tickets", args)

def get_ticket(ticket_id):
	return _call_tool_impl("get_ticket", {"ticket_id": ticket_id})

def create_ticket(project, title, type="task", priority=2, estimation=None, description=""):
	return _call_tool_impl("create_ticket", {
		"project": project, "title": title, "type": type,
		"priority": priority, "estimation": estimation, "description": description,
	})

def update_ticket(ticket_id, title=None, description=None, type=None, estimation=None, priority=None, labels=None, components=None, sprint=None):
	return _call_tool_impl("update_ticket", {
		"ticket_id": ticket_id, "title": title, "description": description,
		"type": type, "estimation": estimation, "priority": priority,
		"labels": labels, "components": components, "sprint": sprint,
	})

def transition_ticket(ticket_id, state):
	return _call_tool_impl("transition_ticket", {"ticket_id": ticket_id, "state": state})

def list_labels(project):
	return _call_tool_impl("list_labels", {"project": project})

def list_components(project):
	return _call_tool_impl("list_components", {"project": project})

def create_component(project, name, description=""):
	return _call_tool_impl("create_component", {"project": project, "name": name, "description": description})

def update_component(component_id, name=None, description=None):
	return _call_tool_impl("update_component", {"component_id": component_id, "name": name, "description": description})

def delete_component(component_id):
	return _call_tool_impl("delete_component", {"component_id": component_id})

def create_label(project, name, color="secondary", description=""):
	return _call_tool_impl("create_label", {"project": project, "name": name, "color": color, "description": description})

def list_attachments(ticket_id):
	return _call_tool_impl("list_attachments", {"ticket_id": ticket_id})

def get_attachment(attachment_id):
	return _call_tool_impl("get_attachment", {"attachment_id": attachment_id})

def delete_attachment(attachment_id):
	return _call_tool_impl("delete_attachment", {"attachment_id": attachment_id})

def upload_attachment(ticket_id, file_path):
	return _call_tool_impl("upload_attachment", {"ticket_id": ticket_id, "file_path": file_path})

def list_sprints(project_key):
	return _call_tool_impl("list_sprints", {"project_key": project_key})

def get_active_sprint_tickets(project_key):
	return _call_tool_impl("get_active_sprint_tickets", {"project_key": project_key})

def create_sprint(project_key, name, description="", start_date=None, end_date=None, order=0, is_active=False):
	return _call_tool_impl("create_sprint", {
		"project_key": project_key, "name": name, "description": description,
		"start_date": start_date, "end_date": end_date, "order": order, "is_active": is_active,
	})

def update_sprint(sprint_id, name=None, description=None, start_date=None, end_date=None, order=None, is_active=None):
	return _call_tool_impl("update_sprint", {
		"sprint_id": sprint_id, "name": name, "description": description,
		"start_date": start_date, "end_date": end_date, "order": order, "is_active": is_active,
	})

def delete_sprint(sprint_id):
	return _call_tool_impl("delete_sprint", {"sprint_id": sprint_id})

def close_sprint(project_key, sprint_id, action="backlog", target_sprint=None):
	return _call_tool_impl("close_sprint", {
		"project_key": project_key, "sprint_id": sprint_id, "action": action, "target_sprint": target_sprint,
	})

def add_relation(ticket_id, target_id, relation_type):
	return _call_tool_impl("add_relation", {"ticket_id": ticket_id, "target_id": target_id, "relation_type": relation_type})

def delete_relation(relation_id):
	return _call_tool_impl("delete_relation", {"relation_id": relation_id})


async def _health(request):
	"""Liveness/readiness probe.

	Reports whether the MCP process is up *and* whether the Django REST API it
	proxies is reachable, so a consuming project can fail fast (``make
	check-tracker``) instead of discovering a dead backend mid-conversation.
	"""
	upstream = "unknown"
	try:
		result = await anyio.to_thread.run_sync(lambda: _request("GET", "/meta/"))
		upstream = "error" if isinstance(result, dict) and result.get("status", 200) >= 400 else "ok"
	except Exception:  # noqa: BLE001
		upstream = "unreachable"
	status = 200 if upstream == "ok" else 503
	return JSONResponse(
		{"status": "ok", "upstream": upstream, "api": API, "tools": len(TOOLS)},
		status_code=status,
	)


def build_http_app():
	"""Build the streamable-HTTP ASGI app.

	``stateless_http=True`` + ``json_response=True`` is the robust configuration
	for editor clients: there is no ``Mcp-Session-Id`` to invalidate, so a server
	restart (or an idle SSE stream timing out) can no longer strand the client
	with 404s on a dead session — the classic "opencode exits early" symptom.
	"""
	return mcp.streamable_http_app(
		streamable_http_path="/mcp",
		json_response=True,
		stateless_http=True,
		host=MCP_HOST,
		custom_starlette_routes=[Route("/health", _health, methods=["GET"])],
	)


async def _run_stdio():
	"""Serve MCP over stdio, for clients that spawn the server as a subprocess."""
	from mcp.server.stdio import stdio_server

	async with stdio_server() as (read_stream, write_stream):
		await mcp.run(read_stream, write_stream, mcp.create_initialization_options())


def main(argv: list[str] | None = None) -> None:
	parser = argparse.ArgumentParser(description="SmartTracking MCP server")
	parser.add_argument(
		"--stdio",
		action="store_true",
		help="serve over stdio instead of streamable HTTP (no port, no session ids)",
	)
	parser.add_argument("--host", default=MCP_HOST)
	parser.add_argument("--port", type=int, default=MCP_PORT)
	opts = parser.parse_args(argv)

	_logger.info("Django API base: %s", API)
	_logger.info("API token: %s", "set" if TOKEN else "not set")

	if opts.stdio:
		# stdout is the MCP transport in this mode — logs MUST stay on stderr.
		_logger.info("Starting SmartTracking MCP server on stdio")
		anyio.run(_run_stdio)
		return

	_logger.info("Starting SmartTracking MCP server on %s:%d", opts.host, opts.port)
	uvicorn.run(
		build_http_app(),
		host=opts.host,
		port=opts.port,
		# Keep idle connections alive far longer than uvicorn's 5 s default so a
		# thinking agent does not get its transport yanked between tool calls.
		timeout_keep_alive=120,
	)


if __name__ == "__main__":
	main()
