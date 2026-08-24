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
"""

import logging
import os
import sys
from typing import Any

import httpx
import uvicorn
from mcp.server import Server
from mcp.types import (
	CallToolResult,
	ListToolsResult,
	TextContent,
	Tool,
)

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


def _client() -> httpx.Client:
	headers = {"Accept": "application/json"}
	if TOKEN:
		headers["Authorization"] = f"Bearer {TOKEN}"
	return httpx.Client(base_url=API, headers=headers, timeout=15)


def _request(method: str, path: str, **kwargs: Any) -> Any:
	"""Call the REST API and return parsed JSON, surfacing errors to the agent."""
	_logger.debug("API %s %s %s", method, path, kwargs.get("json", kwargs.get("params", {})))
	with _client() as client:
		resp = client.request(method, path, **kwargs)
	try:
		body = resp.json()
	except ValueError:
		body = {"error": resp.text}
	if resp.status_code >= 400:
		_logger.debug("API %s %s -> %d", method, path, resp.status_code)
		return {"status": resp.status_code, **body}
	_logger.debug("API %s %s -> %d", method, path, resp.status_code)
	return body


# ── Tool definitions ───────────────────────────────────────────────────────

TOOLS: list[Tool] = [
	Tool(
		name="get_meta",
		description="Return ticket enums (types, states, priorities) and the state-transition graph. Call this first to learn valid values before creating/moving tickets.",
		inputSchema={},
	),
	Tool(
		name="list_projects",
		description="List all projects.",
		inputSchema={},
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
		description="List tickets, optionally filtered by project key and/or state value.",
		inputSchema={
			"type": "object",
			"properties": {
				"project": {"type": "string"},
				"state": {"type": "string"},
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


async def handle_list_tools(*args, **kwargs) -> ListToolsResult:
	return ListToolsResult(tools=TOOLS)


async def handle_call_tool(name: str, arguments: dict = None) -> CallToolResult:
	if arguments is None:
		arguments = {}
	result = _call_tool_impl(name, arguments)
	return CallToolResult(content=[TextContent(text=str(result))])


def _call_tool_impl(name: str, args: dict) -> Any:
	if name == "get_meta":
		return _request("GET", "/meta/")
	elif name == "list_projects":
		return _request("GET", "/projects/")
	elif name == "get_project":
		return _request("GET", f"/projects/{_get_arg(args, 'key', str)}/")
	elif name == "create_project":
		return _request(
			"POST", "/projects/",
			json={"key": _get_arg(args, "key", str), "name": _get_arg(args, "name", str), "description": _get_arg(args, "description", "")},
		)
	elif name == "list_tickets":
		params = {}
		if project := _get_arg(args, "project"):
			params["project"] = project
		if state := _get_arg(args, "state"):
			params["state"] = state
		return _request("GET", "/tickets/", params=params)
	elif name == "get_ticket":
		return _request("GET", f"/tickets/{_get_arg(args, 'ticket_id', int)}/")
	elif name == "create_ticket":
		return _request(
			"POST", "/tickets/",
			json={
				"project": _get_arg(args, "project", str),
				"title": _get_arg(args, "title", str),
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
		return _request("PATCH", f"/tickets/{_get_arg(args, 'ticket_id', int)}/", json=payload)
	elif name == "transition_ticket":
		return _request(
			"POST", f"/tickets/{_get_arg(args, 'ticket_id', int)}/transition/",
			json={"state": _get_arg(args, "state", str)},
		)
	elif name == "list_labels":
		return _request("GET", "/labels/", params={"project": _get_arg(args, "project", str)})
	elif name == "list_components":
		return _request("GET", "/components/", params={"project": _get_arg(args, "project", str)})
	elif name == "create_component":
		return _request(
			"POST", "/components/",
			json={"project": _get_arg(args, "project", str), "name": _get_arg(args, "name", str), "description": _get_arg(args, "description", "")},
		)
	elif name == "update_component":
		payload = {
			k: v
			for k, v in {"name": _get_arg(args, "name"), "description": _get_arg(args, "description")}.items()
			if v is not None
		}
		return _request("PATCH", f"/components/{_get_arg(args, 'component_id', int)}/", json=payload)
	elif name == "delete_component":
		return _request("DELETE", f"/components/{_get_arg(args, 'component_id', int)}/")
	elif name == "create_label":
		return _request(
			"POST", "/labels/",
			json={"project": _get_arg(args, "project", str), "name": _get_arg(args, "name", str), "color": _get_arg(args, "color", "secondary"), "description": _get_arg(args, "description", "")},
		)
	elif name == "list_attachments":
		return _request("GET", "/attachments/", params={"ticket": _get_arg(args, "ticket_id", int)})
	elif name == "get_attachment":
		return _request("GET", f"/attachments/{_get_arg(args, 'attachment_id', int)}/")
	elif name == "delete_attachment":
		return _request("DELETE", f"/attachments/{_get_arg(args, 'attachment_id', int)}/")
	elif name == "upload_attachment":
		ticket_id = _get_arg(args, "ticket_id", int)
		file_path = _get_arg(args, "file_path", str)
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
		return _request("GET", f"/sprints/{_get_arg(args, 'project_key', str)}/")
	elif name == "get_active_sprint_tickets":
		return _request("GET", f"/sprints/{_get_arg(args, 'project_key', str)}/active/tickets/")
	elif name == "create_sprint":
		return _request(
			"POST", f"/sprints/{_get_arg(args, 'project_key', str)}/create/",
			json={
				"name": _get_arg(args, "name", str),
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
		return _request("PATCH", f"/sprints/{_get_arg(args, 'sprint_id', int)}/", json=payload)
	elif name == "delete_sprint":
		return _request("DELETE", f"/sprints/{_get_arg(args, 'sprint_id', int)}/")
	elif name == "close_sprint":
		return _request(
			"POST", f"/sprints/{_get_arg(args, 'project_key', str)}/{_get_arg(args, 'sprint_id', int)}/close/",
			json={"action": _get_arg(args, "action", "backlog"), "target_sprint": _get_arg(args, "target_sprint")},
		)
	elif name == "add_relation":
		return _request(
			"POST", f"/tickets/{_get_arg(args, 'ticket_id', int)}/relations/add/",
			json={"target_id": _get_arg(args, "target_id", int), "relation_type": _get_arg(args, "relation_type", str)},
		)
	elif name == "delete_relation":
		return _request("DELETE", f"/tickets/relations/{_get_arg(args, 'relation_id', int)}/delete/")
	else:
		return {"error": f"Unknown tool: {name}"}


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

def list_tickets(project=None, state=None):
	args = {}
	if project:
		args["project"] = project
	if state:
		args["state"] = state
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


if __name__ == "__main__":
	_logger.info("Starting SmartTracking MCP server on %s:%d", MCP_HOST, MCP_PORT)
	_logger.info("Django API base: %s", API)
	_logger.info("API token: %s", "set" if TOKEN else "not set")
	# Streamable HTTP transport -> reachable at http://MCP_HOST:MCP_PORT/mcp
	app = mcp.streamable_http_app()
	uvicorn.run(app, host=MCP_HOST, port=MCP_PORT)
