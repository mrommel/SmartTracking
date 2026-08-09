"""Tests for the MCP server tools (mcp_server.py).

Each test patches ``_request`` to verify that the MCP tool calls the correct
REST endpoint with the expected method, path, and parameters — without needing
the Django dev server running.
"""

from unittest.mock import patch, call

from django.test import TestCase

# Import the module-level _request so we can patch it.
# The tools call the local _request, not the one we import.
import mcp_server as mcp_mod


@patch.object(mcp_mod, "_request")
class McpToolTests(TestCase):
	"""Every @mcp.tool() should delegate to ``_request`` with the right args."""

	# --- Discovery -----------------------------------------------------------

	def test_get_meta(self, mock_req):
		mcp_mod.get_meta()
		mock_req.assert_called_once_with("GET", "/meta/")

	# --- Projects ------------------------------------------------------------

	def test_list_projects(self, mock_req):
		mcp_mod.list_projects()
		mock_req.assert_called_once_with("GET", "/projects/")

	def test_get_project(self, mock_req):
		mcp_mod.get_project("SMT")
		mock_req.assert_called_once_with("GET", "/projects/SMT/")

	def test_create_project(self, mock_req):
		mcp_mod.create_project("SMT", "SmartTracking", "Tracker")
		mock_req.assert_called_once_with(
			"POST", "/projects/",
			json={"key": "SMT", "name": "SmartTracking", "description": "Tracker"},
		)

	def test_create_project_defaults_description(self, mock_req):
		mcp_mod.create_project("ABC", "Alpha")
		mock_req.assert_called_once_with(
			"POST", "/projects/",
			json={"key": "ABC", "name": "Alpha", "description": ""},
		)

	# --- Tickets -------------------------------------------------------------

	def test_list_tickets_no_filters(self, mock_req):
		mcp_mod.list_tickets()
		mock_req.assert_called_once_with("GET", "/tickets/", params={})

	def test_list_tickets_with_project(self, mock_req):
		mcp_mod.list_tickets(project="SMT")
		mock_req.assert_called_once_with("GET", "/tickets/", params={"project": "SMT"})

	def test_list_tickets_with_state(self, mock_req):
		mcp_mod.list_tickets(state="open")
		mock_req.assert_called_once_with("GET", "/tickets/", params={"state": "open"})

	def test_list_tickets_with_both_filters(self, mock_req):
		mcp_mod.list_tickets(project="SMT", state="open")
		mock_req.assert_called_once_with(
			"GET", "/tickets/", params={"project": "SMT", "state": "open"},
		)

	def test_get_ticket(self, mock_req):
		mcp_mod.get_ticket(42)
		mock_req.assert_called_once_with("GET", "/tickets/42/")

	def test_create_ticket_defaults(self, mock_req):
		mcp_mod.create_ticket("SMT", "New ticket")
		mock_req.assert_called_once_with(
			"POST", "/tickets/",
			json={
				"project": "SMT",
				"title": "New ticket",
				"type": "task",
				"priority": 2,
				"description": "",
			},
		)

	def test_create_ticket_full(self, mock_req):
		mcp_mod.create_ticket("SMT", "Bug report", type="bug", priority=4, description="Details")
		mock_req.assert_called_once_with(
			"POST", "/tickets/",
			json={
				"project": "SMT",
				"title": "Bug report",
				"type": "bug",
				"priority": 4,
				"description": "Details",
			},
		)

	def test_update_ticket_minimal(self, mock_req):
		mcp_mod.update_ticket(1, title="Updated")
		mock_req.assert_called_once_with(
			"PATCH", "/tickets/1/",
			json={"title": "Updated"},
		)

	def test_update_ticket_with_labels(self, mock_req):
		mcp_mod.update_ticket(1, labels=["urgent"])
		mock_req.assert_called_once_with(
			"PATCH", "/tickets/1/",
			json={"labels": ["urgent"]},
		)

	def test_update_ticket_with_components(self, mock_req):
		mcp_mod.update_ticket(1, components=["frontend"])
		mock_req.assert_called_once_with(
			"PATCH", "/tickets/1/",
			json={"components": ["frontend"]},
		)

	def test_update_ticket_all_fields(self, mock_req):
		mcp_mod.update_ticket(
			1, title="T", description="D", type="bug", priority=3,
			labels=["urgent"], components=["api"],
		)
		mock_req.assert_called_once_with(
			"PATCH", "/tickets/1/",
			json={
				"title": "T",
				"description": "D",
				"type": "bug",
				"priority": 3,
				"labels": ["urgent"],
				"components": ["api"],
			},
		)

	def test_update_ticket_omits_none(self, mock_req):
		"""Only non-None fields should appear in the payload."""
		mcp_mod.update_ticket(1, title="T")
		payload = mock_req.call_args[1]["json"]
		self.assertNotIn("description", payload)
		self.assertNotIn("type", payload)
		self.assertNotIn("priority", payload)
		self.assertNotIn("labels", payload)
		self.assertNotIn("components", payload)

	def test_transition_ticket(self, mock_req):
		mcp_mod.transition_ticket(42, "in_progress")
		mock_req.assert_called_once_with(
			"POST", "/tickets/42/transition/", json={"state": "in_progress"},
		)

	# --- Labels & Components --------------------------------------------------

	def test_list_labels(self, mock_req):
		mcp_mod.list_labels("SMT")
		mock_req.assert_called_once_with("GET", "/labels/", params={"project": "SMT"})

	def test_list_components(self, mock_req):
		mcp_mod.list_components("SMT")
		mock_req.assert_called_once_with("GET", "/components/", params={"project": "SMT"})

	def test_create_component(self, mock_req):
		mcp_mod.create_component("SMT", "frontend", "UI layer")
		mock_req.assert_called_once_with(
			"POST", "/components/",
			json={"project": "SMT", "name": "frontend", "description": "UI layer"},
		)

	def test_create_component_defaults_description(self, mock_req):
		mcp_mod.create_component("SMT", "backend")
		mock_req.assert_called_once_with(
			"POST", "/components/",
			json={"project": "SMT", "name": "backend", "description": ""},
		)

	def test_create_label(self, mock_req):
		mcp_mod.create_label("SMT", "urgent", "red", "Needs immediate attention")
		mock_req.assert_called_once_with(
			"POST", "/labels/",
			json={"project": "SMT", "name": "urgent", "color": "red", "description": "Needs immediate attention"},
		)

	def test_create_label_defaults(self, mock_req):
		mcp_mod.create_label("SMT", "blocked")
		mock_req.assert_called_once_with(
			"POST", "/labels/",
			json={"project": "SMT", "name": "blocked", "color": "secondary", "description": ""},
		)
