"""Tests for the MCP server tools (mcp_server.py).

Each test patches ``_request`` to verify that the MCP tool calls the correct
REST endpoint with the expected method, path, and parameters — without needing
the Django dev server running.

``McpWireProtocolTests`` additionally covers the *transport* path
(``handle_call_tool`` / ``handle_list_tools``), which the tool tests above
deliberately bypass by calling the module-level wrappers directly.
"""

import asyncio
import json
from unittest.mock import patch

# Import the module-level _request so we can patch it.
# The tools call the local _request, not the one we import.
import mcp_server as mcp_mod
import httpx
from django.test import TestCase
from mcp.types import CallToolRequestParams


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

	def test_get_active_sprint_tickets(self, mock_req):
		mcp_mod.get_active_sprint_tickets("SMT")
		mock_req.assert_called_once_with("GET", "/sprints/SMT/active/tickets/")

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


class McpWireProtocolTests(TestCase):
	"""Guard the MCP transport seam, not just the REST delegation.

	The low-level ``Server`` invokes handlers as ``handler(ctx, params)``.  A
	previous signature of ``handle_call_tool(name, arguments)`` meant the
	*context object* was treated as the tool name, so every call over the wire
	fell through to the "Unknown tool" branch — while the delegation tests above
	stayed green because they never touch the handler.
	"""

	def _call(self, name, arguments=None):
		# GIVEN a tools/call request as the low-level Server would deliver it
		params = CallToolRequestParams(name=name, arguments=arguments or {})
		# WHEN the registered handler processes it
		return asyncio.run(mcp_mod.handle_call_tool(None, params))

	def test_call_tool_dispatches_by_params_name(self):
		# GIVEN a stubbed upstream
		with patch.object(mcp_mod, "_request", return_value={"ok": True}) as mock_req:
			# WHEN a tool is called through the wire handler
			result = self._call("get_meta")
		# THEN the correct REST endpoint is hit, not the unknown-tool branch
		mock_req.assert_called_once_with("GET", "/meta/")
		self.assertFalse(result.is_error)

	def test_call_tool_returns_json_not_python_repr(self):
		# GIVEN an upstream payload containing values whose repr is not JSON
		with patch.object(mcp_mod, "_request", return_value={"id": 1, "estimation": None, "done": True}):
			# WHEN the tool is called
			result = self._call("get_ticket", {"ticket_id": 1})
		# THEN the content is parseable JSON (``None``/``True`` would break it)
		payload = json.loads(result.content[0].text)
		self.assertEqual(payload, {"id": 1, "estimation": None, "done": True})
		self.assertEqual(result.content[0].type, "text")

	def test_call_tool_flags_upstream_error_status(self):
		# GIVEN an upstream rejection
		with patch.object(mcp_mod, "_request", return_value={"status": 409, "error": "illegal"}):
			# WHEN an illegal transition is attempted
			result = self._call("transition_ticket", {"ticket_id": 1, "state": "closed"})
		# THEN it is surfaced as an MCP tool error, not a silent success
		self.assertTrue(result.is_error)

	def test_call_tool_rejects_missing_required_argument(self):
		# GIVEN a call that omits a required argument
		with patch.object(mcp_mod, "_request") as mock_req:
			result = self._call("get_project", {})
		# THEN no bogus request is made and the agent gets a usable error
		self.assertFalse(mock_req.called)
		self.assertTrue(result.is_error)
		self.assertIn("key", json.loads(result.content[0].text)["error"])

	def test_call_tool_unknown_name_is_error_with_suggestion(self):
		# GIVEN a hallucinated near-miss tool name
		result = self._call("get_tickets")
		# THEN the response is an error carrying a correction hint
		payload = json.loads(result.content[0].text)
		self.assertTrue(result.is_error)
		self.assertIn("get_ticket", payload["did_you_mean"])

	def test_call_tool_survives_unexpected_exception(self):
		# GIVEN an upstream that blows up
		with patch.object(mcp_mod, "_request", side_effect=RuntimeError("boom")):
			result = self._call("get_meta")
		# THEN the session survives and the failure is reported as a tool error
		self.assertTrue(result.is_error)
		self.assertIn("boom", result.content[0].text)

	def test_every_tool_advertises_an_object_input_schema(self):
		# GIVEN the advertised tool list
		result = asyncio.run(mcp_mod.handle_list_tools(None, None))
		# THEN every schema is a JSON-Schema object; a bare {} makes strict
		# clients reject the whole tools/list result and drop the session.
		for tool in result.tools:
			self.assertEqual((tool.input_schema or {}).get("type"), "object", tool.name)

	def test_list_tools_exposes_all_tools(self):
		# GIVEN the handler
		result = asyncio.run(mcp_mod.handle_list_tools(None, None))
		# THEN it mirrors the TOOLS registry
		self.assertEqual(len(result.tools), len(mcp_mod.TOOLS))


class McpUpstreamUnreachableTests(TestCase):
	"""A stopped Django app must yield a readable 503, never an httpx traceback."""

	def _fail(self, exc):
		return patch.object(mcp_mod, "_client", side_effect=exc)

	def test_request_retries_then_reports_connection_error(self):
		# GIVEN an upstream that always refuses the connection
		with patch.object(mcp_mod, "_TRANSPORT_RETRY_DELAY", 0), self._fail(httpx.ConnectError("refused")):
			payload = mcp_mod._request("GET", "/meta/")
		# THEN the tool gets an actionable error instead of an exception
		self.assertEqual(payload["status"], 503)
		self.assertIn("unreachable", payload["error"])
		self.assertIn("make run", payload["hint"])

	def test_request_retries_before_giving_up(self):
		# GIVEN an upstream that recovers on the last attempt
		attempts = []

		def flaky():
			attempts.append(1)
			if len(attempts) < 3:
				raise httpx.ConnectError("refused")
			return _StubClient({"ok": True})

		with patch.object(mcp_mod, "_TRANSPORT_RETRY_DELAY", 0), patch.object(mcp_mod, "_client", side_effect=flaky):
			payload = mcp_mod._request("GET", "/meta/")
		# THEN the transient failure is absorbed
		self.assertEqual(payload, {"ok": True})
		self.assertEqual(len(attempts), 3)

	def test_timeout_is_reported_as_timeout(self):
		# GIVEN a stalled upstream
		with patch.object(mcp_mod, "_TRANSPORT_RETRY_DELAY", 0), self._fail(httpx.ReadTimeout("slow")):
			payload = mcp_mod._request("GET", "/meta/")
		# THEN the error names the timeout kind
		self.assertIn("timeout", payload["error"])

	def test_unreachable_upstream_is_flagged_as_tool_error(self):
		# GIVEN a tool call against a dead upstream
		with patch.object(mcp_mod, "_TRANSPORT_RETRY_DELAY", 0), self._fail(httpx.ConnectError("refused")):
			result = asyncio.run(
				mcp_mod.handle_call_tool(None, CallToolRequestParams(name="get_meta", arguments={}))
			)
		# THEN the session survives and the client sees the 503 payload
		self.assertTrue(result.is_error)
		self.assertEqual(json.loads(result.content[0].text)["status"], 503)


class _StubClient:
	"""Minimal ``httpx.Client`` stand-in usable as a context manager."""

	def __init__(self, payload, status_code=200):
		self._payload = payload
		self.status_code = status_code

	def __enter__(self):
		return self

	def __exit__(self, *exc_info):
		return False

	def request(self, *args, **kwargs):
		return self

	def json(self):
		return self._payload


class McpPaginationTests(TestCase):
	"""``list_tickets`` must be able to page instead of dumping whole projects."""

	def test_list_tickets_forwards_paging_params(self):
		# GIVEN a paged request
		with patch.object(mcp_mod, "_request") as mock_req:
			mcp_mod.list_tickets(project="SWG", page=2, page_size=50)
		# THEN the page params reach the REST layer
		mock_req.assert_called_once_with(
			"GET", "/tickets/", params={"page": 2, "page_size": 50, "project": "SWG"},
		)

	def test_list_tickets_without_paging_is_unchanged(self):
		# GIVEN no paging arguments
		with patch.object(mcp_mod, "_request") as mock_req:
			mcp_mod.list_tickets()
		# THEN the call is identical to the legacy behaviour
		mock_req.assert_called_once_with("GET", "/tickets/", params={})

