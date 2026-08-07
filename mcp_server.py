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
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

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
	with _client() as client:
		resp = client.request(method, path, **kwargs)
	try:
		body = resp.json()
	except ValueError:
		body = {"error": resp.text}
	if resp.status_code >= 400:
		return {"status": resp.status_code, **body}
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
	description: str = "",
) -> Any:
	"""Create a ticket in a project. `type` is one of task/bug/story/epic;
	`priority` is 1..4 (low..critical). See `get_meta` for exact values."""
	return _request(
		"POST", "/tickets/",
		json={
			"project": project,
			"title": title,
			"type": type,
			"priority": priority,
			"description": description,
		},
	)


@mcp.tool()
def update_ticket(
	ticket_id: int,
	title: Optional[str] = None,
	description: Optional[str] = None,
	type: Optional[str] = None,
	priority: Optional[int] = None,
) -> Any:
	"""Partially update a ticket's fields. To change the state, use
	`transition_ticket` instead (this endpoint rejects a 'state' key)."""
	payload = {
		k: v
		for k, v in {
			"title": title,
			"description": description,
			"type": type,
			"priority": priority,
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


if __name__ == "__main__":
	# Streamable HTTP transport -> reachable at http://MCP_HOST:MCP_PORT/mcp
	mcp.run(transport="streamable-http")

