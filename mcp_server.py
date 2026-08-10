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

import os
import sys
import logging
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

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

mcp = FastMCP("smarttracking", host=MCP_HOST, port=MCP_PORT)


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


@mcp.tool()
def get_meta() -> Any:
	"""Return ticket enums (types, states, priorities) and the state-transition
	graph. Call this first to learn valid values before creating/moving tickets."""
	return _request("GET", "/meta/")


@mcp.tool()
def list_projects() -> Any:
	"""List all projects."""
	return _request("GET", "/projects/")


@mcp.tool()
def get_project(key: str) -> Any:
	"""Get a single project by its uppercase key (e.g. 'SMT')."""
	return _request("GET", f"/projects/{key}/")


@mcp.tool()
def create_project(key: str, name: str, description: str = "") -> Any:
	"""Create a project. `key` is a short uppercase identifier used as the
	ticket-ID prefix (e.g. 'SMT'). Returns status 409 if the key already exists."""
	return _request(
		"POST", "/projects/",
		json={"key": key, "name": name, "description": description},
	)


@mcp.tool()
def list_tickets(project: Optional[str] = None, state: Optional[str] = None) -> Any:
	"""List tickets, optionally filtered by project key and/or state value."""
	params = {}
	if project:
		params["project"] = project
	if state:
		params["state"] = state
	return _request("GET", "/tickets/", params=params)


@mcp.tool()
def get_ticket(ticket_id: int) -> Any:
	"""Get a single ticket by numeric id. The response includes
	`allowed_transitions` for the current state."""
	return _request("GET", f"/tickets/{ticket_id}/")


@mcp.tool()
def create_ticket(
	project: str,
	title: str,
	type: str = "task",
	priority: int = 2,
	estimation: Optional[int] = None,
	description: str = "",
) -> Any:
	"""Create a ticket in a project. `type` is one of task/bug/story/epic;
	`priority` is 1..4 (low..critical). `estimation` is an optional integer.
	See `get_meta` for exact values."""
	return _request(
		"POST", "/tickets/",
		json={
			"project": project,
			"title": title,
			"type": type,
			"priority": priority,
			"estimation": estimation,
			"description": description,
		},
	)


@mcp.tool()
def update_ticket(
	ticket_id: int,
	title: Optional[str] = None,
	description: Optional[str] = None,
	type: Optional[str] = None,
	estimation: Optional[int] = None,
	priority: Optional[int] = None,
	labels: Optional[list[str]] = None,
	components: Optional[list[str]] = None,
) -> Any:
	"""Partially update a ticket's fields. To change the state, use
	`transition_ticket` instead (this endpoint rejects a 'state' key).
	`labels` and `components` accept a list of label/component names for the
	project; unknown names are silently ignored."""
	payload = {
		k: v
		for k, v in {
			"title": title,
			"description": description,
			"type": type,
			"estimation": estimation,
			"priority": priority,
			"labels": labels,
			"components": components,
		}.items()
		if v is not None
	}
	return _request("PATCH", f"/tickets/{ticket_id}/", json=payload)


@mcp.tool()
def transition_ticket(ticket_id: int, state: str) -> Any:
	"""Move a ticket to a new state, honouring the transition graph. On an
	illegal move returns status 409 with the list of `allowed_transitions`."""
	return _request(
		"POST", f"/tickets/{ticket_id}/transition/", json={"state": state}
	)


@mcp.tool()
def list_labels(project: str) -> Any:
	"""List all labels defined for a project. Use this to learn valid label
	names before setting them on a ticket via `update_ticket`."""
	return _request("GET", "/labels/", params={"project": project})


@mcp.tool()
def list_components(project: str) -> Any:
	"""List all components defined for a project. Use this to learn valid
	component names before setting them on a ticket via `update_ticket`."""
	return _request("GET", "/components/", params={"project": project})


@mcp.tool()
def create_component(
	project: str,
	name: str,
	description: str = "",
) -> Any:
	"""Create a component for a project. Returns status 409 if the name already
	exists in that project."""
	return _request(
		"POST", "/components/",
		json={"project": project, "name": name, "description": description},
	)


@mcp.tool()
def update_component(
	component_id: int,
	name: Optional[str] = None,
	description: Optional[str] = None,
) -> Any:
	"""Partially update a component's fields. Any field not provided is left
	unchanged. Returns 404 if the component does not exist."""
	payload = {
		k: v
		for k, v in {"name": name, "description": description}.items()
		if v is not None
	}
	return _request("PATCH", f"/components/{component_id}/", json=payload)


@mcp.tool()
def delete_component(component_id: int) -> Any:
	"""Delete a component. Tickets that referenced this component will no longer
	have it assigned."""
	return _request("DELETE", f"/components/{component_id}/")


@mcp.tool()
def create_label(
	project: str,
	name: str,
	color: str = "secondary",
	description: str = "",
) -> Any:
	"""Create a label for a project. Returns status 409 if the name already
	exists in that project. `color` is a Bootstrap badge color (default
	"secondary")."""
	return _request(
		"POST", "/labels/",
		json={"project": project, "name": name, "color": color, "description": description},
	)


def _upload_file(ticket_id: int, file_path: str) -> Any:
	"""Upload a file to a ticket using multipart form data."""
	import os as _os
	with _client() as client:
		try:
			with open(file_path, "rb") as f:
				resp = client.post(
					f"/attachments/",
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


@mcp.tool()
def list_attachments(ticket_id: int) -> Any:
	"""List all attachments for a ticket."""
	return _request("GET", "/attachments/", params={"ticket": ticket_id})


@mcp.tool()
def get_attachment(attachment_id: int) -> Any:
	"""Get a single attachment by numeric id."""
	return _request("GET", f"/attachments/{attachment_id}/")


@mcp.tool()
def delete_attachment(attachment_id: int) -> Any:
	"""Delete an attachment. The file is permanently removed."""
	return _request("DELETE", f"/attachments/{attachment_id}/")


@mcp.tool()
def upload_attachment(ticket_id: int, file_path: str) -> Any:
	"""Upload a file to a ticket. The file must exist on the local filesystem.
	Allowed extensions: png, jpg, jpeg, pdf, txt, log, json."""
	return _upload_file(ticket_id, file_path)


# --- Sprints ---------------------------------------------------------------

@mcp.tool()
def list_sprints(project_key: str) -> Any:
	"""List all sprints for a project. Returns list of sprints with their
	ids, names, dates, and active status."""
	return _request("GET", f"/sprints/{project_key}/")


@mcp.tool()
def create_sprint(project_key: str, name: str, description: str = "", start_date: Optional[str] = None, end_date: Optional[str] = None, order: int = 0, is_active: bool = False) -> Any:
	"""Create a sprint in a project. Returns status 409 if the name already
	exists in that project. `order` controls display order; `is_active` makes
	this the current active sprint (deactivating any other active sprint in
	the same project)."""
	return _request(
		"POST", f"/sprints/{project_key}/create/",
		json={
			"name": name,
			"description": description,
			"start_date": start_date,
			"end_date": end_date,
			"order": order,
			"is_active": is_active,
		},
	)


@mcp.tool()
def update_sprint(
	sprint_id: int,
	name: Optional[str] = None,
	description: Optional[str] = None,
	start_date: Optional[str] = None,
	end_date: Optional[str] = None,
	order: Optional[int] = None,
	is_active: Optional[bool] = None,
) -> Any:
	"""Partially update a sprint's fields. Any field not provided is left
	unchanged. Returns 404 if the sprint does not exist. Setting
	`is_active=True` deactivates any other active sprint in the same project."""
	payload = {
		k: v
		for k, v in {
			"name": name,
			"description": description,
			"start_date": start_date,
			"end_date": end_date,
			"order": order,
			"is_active": is_active,
		}.items()
		if v is not None
	}
	return _request("PATCH", f"/sprints/{sprint_id}/", json=payload)


@mcp.tool()
def delete_sprint(sprint_id: int) -> Any:
	"""Delete a sprint. Cannot delete the backlog pseudo-sprint (pk=1).
	Returns status 403 if deletion is not allowed."""
	return _request("DELETE", f"/sprints/{sprint_id}/")


# --- Relations -------------------------------------------------------------

@mcp.tool()
def add_relation(ticket_id: int, target_id: int, relation_type: str) -> Any:
	"""Create a relation from one ticket to another within the same project.
	`relation_type` is one of: related_to, blocked_by, tested_with.
	Returns status 409 if the relation already exists or tickets are in
	different projects."""
	return _request(
		"POST", f"/tickets/{ticket_id}/relations/add/",
		json={"target_id": target_id, "relation_type": relation_type},
	)


@mcp.tool()
def delete_relation(relation_id: int) -> Any:
	"""Delete a ticket relation. Returns status 404 if not found. Note:
	this endpoint has a known bug and currently raises an AttributeError
	when deleting relations with inverse types (blocked_by, tested_with)."""
	return _request("DELETE", f"/tickets/relations/{relation_id}/delete/")


if __name__ == "__main__":
	_logger.info("Starting SmartTracking MCP server on %s:%d", MCP_HOST, MCP_PORT)
	_logger.info("Django API base: %s", API)
	_logger.info("API token: %s", "set" if TOKEN else "not set")
	# Streamable HTTP transport -> reachable at http://MCP_HOST:MCP_PORT/mcp
	mcp.run(transport="streamable-http")
