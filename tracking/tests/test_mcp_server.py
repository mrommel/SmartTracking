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
				"estimation": None,
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
				"estimation": None,
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

	def test_update_component(self, mock_req):
		mcp_mod.update_component(1, name="frontend-v2")
		mock_req.assert_called_once_with(
			"PATCH", "/components/1/",
			json={"name": "frontend-v2"},
		)

	def test_update_component_all_fields(self, mock_req):
		mcp_mod.update_component(1, name="new", description="desc")
		mock_req.assert_called_once_with(
			"PATCH", "/components/1/",
			json={"name": "new", "description": "desc"},
		)

	def test_update_component_no_fields(self, mock_req):
		mcp_mod.update_component(1)
		mock_req.assert_called_once_with(
			"PATCH", "/components/1/",
			json={},
		)

	def test_delete_component(self, mock_req):
		mcp_mod.delete_component(42)
		mock_req.assert_called_once_with("DELETE", "/components/42/")

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

	# --- Attachments ----------------------------------------------------------

	def test_list_attachments(self, mock_req):
		mcp_mod.list_attachments(42)
		mock_req.assert_called_once_with("GET", "/attachments/", params={"ticket": 42})

	def test_get_attachment(self, mock_req):
		mcp_mod.get_attachment(7)
		mock_req.assert_called_once_with("GET", "/attachments/7/")

	def test_delete_attachment(self, mock_req):
		mcp_mod.delete_attachment(7)
		mock_req.assert_called_once_with("DELETE", "/attachments/7/")

	# --- Sprints --------------------------------------------------------------

	def test_list_sprints(self, mock_req):
		mcp_mod.list_sprints("SMT")
		mock_req.assert_called_once_with("GET", "/sprints/SMT/")

	def test_create_sprint_defaults(self, mock_req):
		mcp_mod.create_sprint("SMT", "Sprint 1")
		mock_req.assert_called_once_with(
			"POST", "/sprints/SMT/create/",
			json={
				"name": "Sprint 1",
				"description": "",
				"start_date": None,
				"end_date": None,
				"order": 0,
				"is_active": False,
			},
		)

	def test_create_sprint_full(self, mock_req):
		mcp_mod.create_sprint(
			"SMT", "Sprint 2",
			description="Q2 planning",
			start_date="2025-04-01",
			end_date="2025-04-14",
			order=2,
			is_active=True,
		)
		mock_req.assert_called_once_with(
			"POST", "/sprints/SMT/create/",
			json={
				"name": "Sprint 2",
				"description": "Q2 planning",
				"start_date": "2025-04-01",
				"end_date": "2025-04-14",
				"order": 2,
				"is_active": True,
			},
		)

	def test_update_sprint_minimal(self, mock_req):
		mcp_mod.update_sprint(1, name="Updated Sprint")
		mock_req.assert_called_once_with(
			"PATCH", "/sprints/1/",
			json={"name": "Updated Sprint"},
		)

	def test_update_sprint_all_fields(self, mock_req):
		mcp_mod.update_sprint(
			1, description="New", start_date="2025-05-01",
			end_date="2025-05-14", order=3, is_active=True,
		)
		mock_req.assert_called_once_with(
			"PATCH", "/sprints/1/",
			json={
				"description": "New",
				"start_date": "2025-05-01",
				"end_date": "2025-05-14",
				"order": 3,
				"is_active": True,
			},
		)

	def test_update_sprint_omits_none(self, mock_req):
		"""Only non-None fields should appear in the payload."""
		mcp_mod.update_sprint(1, name="T")
		payload = mock_req.call_args[1]["json"]
		self.assertNotIn("description", payload)
		self.assertNotIn("start_date", payload)
		self.assertNotIn("end_date", payload)
		self.assertNotIn("order", payload)
		self.assertNotIn("is_active", payload)

	def test_update_sprint_all_none(self, mock_req):
		mcp_mod.update_sprint(1)
		mock_req.assert_called_once_with(
			"PATCH", "/sprints/1/",
			json={},
		)

	def test_delete_sprint(self, mock_req):
		mcp_mod.delete_sprint(42)
		mock_req.assert_called_once_with("DELETE", "/sprints/42/")

	# --- Relations ------------------------------------------------------------

	def test_add_relation(self, mock_req):
		mcp_mod.add_relation(1, 2, "blocked_by")
		mock_req.assert_called_once_with(
			"POST", "/tickets/1/relations/add/",
			json={"target_id": 2, "relation_type": "blocked_by"},
		)

	def test_add_relation_related_to(self, mock_req):
		mcp_mod.add_relation(5, 10, "related_to")
		mock_req.assert_called_once_with(
			"POST", "/tickets/5/relations/add/",
			json={"target_id": 10, "relation_type": "related_to"},
		)

	def test_delete_relation(self, mock_req):
		mcp_mod.delete_relation(99)
		mock_req.assert_called_once_with("DELETE", "/tickets/relations/99/delete/")
