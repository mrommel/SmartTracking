"""JSON REST API tests: auth layer + endpoint behaviour."""

import json

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from tracking.models import Attachment, Component, Label, Notification, Project, Sprint, Ticket, TicketRelation, Watcher

User = get_user_model()

TOKEN = "test-token-123"


@override_settings(TRACKING_API_TOKEN=TOKEN)
class ApiSchemaTests(TestCase):
	def test_schema_returns_valid_json(self):
		response = self.client.get(
			reverse("api_schema"), HTTP_AUTHORIZATION=f"Bearer {TOKEN}"
		)
		self.assertEqual(response.status_code, 200)
		data = response.json()
		self.assertEqual(data["openapi"], "3.1.0")
		self.assertIn("paths", data)
		self.assertIn("components", data)
		self.assertIn("tags", data)
		self.assertEqual(data["info"]["title"], "SmartTracking REST API")
		# Verify core paths are present
		self.assertIn("/tracking/api/meta/", data["paths"])
		self.assertIn("/tracking/api/tickets/", data["paths"])
		self.assertIn("/tracking/api/projects/", data["paths"])

	def test_schema_requires_auth(self):
		response = self.client.get(reverse("api_schema"))
		self.assertEqual(response.status_code, 401)

	def test_schema_includes_ticket_schemas(self):
		response = self.client.get(
			reverse("api_schema"), HTTP_AUTHORIZATION=f"Bearer {TOKEN}"
		)
		data = response.json()
		components = data["components"]["schemas"]
		self.assertIn("Ticket", components)
		self.assertIn("CreateTicket", components)
		self.assertIn("UpdateTicket", components)
		self.assertIn("Comment", components)
		self.assertIn("Component", components)
		self.assertIn("Label", components)
		self.assertIn("Sprint", components)
		self.assertIn("Attachment", components)

	def test_schema_uses_security_schemes(self):
		response = self.client.get(
			reverse("api_schema"), HTTP_AUTHORIZATION=f"Bearer {TOKEN}"
		)
		data = response.json()
		schemes = data["components"]["securitySchemes"]
		self.assertIn("Bearer", schemes)
		self.assertIn("Cookie", schemes)


@override_settings(TRACKING_API_TOKEN=TOKEN)
class PaginationTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")

	def _auth(self):
		return {"HTTP_AUTHORIZATION": f"Bearer {TOKEN}"}

	def test_single_page_no_next_or_previous(self):
		Ticket.objects.create(project=self.project, title="a")
		Ticket.objects.create(project=self.project, title="b")
		resp = self.client.get(reverse("api_ticket_collection"), **self._auth())
		data = resp.json()
		self.assertEqual(data["count"], 2)
		self.assertEqual(len(data["results"]), 2)
		self.assertIsNone(data["pagination"]["next"])
		self.assertIsNone(data["pagination"]["previous"])

	def test_multiple_pages_next_url(self):
		for i in range(5):
			Ticket.objects.create(project=self.project, title=f"t{i}")
		resp = self.client.get(
			reverse("api_ticket_collection") + "?page_size=2",
			**self._auth(),
		)
		data = resp.json()
		self.assertEqual(data["count"], 5)
		self.assertEqual(len(data["results"]), 2)
		self.assertIsNotNone(data["pagination"]["next"])
		self.assertIn("page=2", data["pagination"]["next"])
		self.assertIsNone(data["pagination"]["previous"])

	def test_multiple_pages_previous_url(self):
		for i in range(5):
			Ticket.objects.create(project=self.project, title=f"t{i}")
		resp = self.client.get(
			reverse("api_ticket_collection") + "?page=2&page_size=2",
			**self._auth(),
		)
		data = resp.json()
		self.assertEqual(len(data["results"]), 2)
		self.assertIsNotNone(data["pagination"]["previous"])
		self.assertIn("page=1", data["pagination"]["previous"])
		self.assertIsNotNone(data["pagination"]["next"])

	def test_page_size_max_capped_at_100(self):
		for i in range(200):
			Ticket.objects.create(project=self.project, title=f"t{i}")
		resp = self.client.get(
			reverse("api_ticket_collection") + "?page_size=999",
			**self._auth(),
		)
		data = resp.json()
		self.assertLessEqual(len(data["results"]), 100)
		self.assertEqual(data["count"], 200)

	def test_default_page_size_is_25(self):
		for i in range(30):
			Ticket.objects.create(project=self.project, title=f"t{i}")
		resp = self.client.get(reverse("api_ticket_collection"), **self._auth())
		data = resp.json()
		self.assertEqual(len(data["results"]), 25)
		self.assertEqual(data["count"], 30)

	def test_list_projects_paginated(self):
		for i in range(5):
			Project.objects.create(key=f"P{i}", name=f"Project {i}")
		resp = self.client.get(
			reverse("api_project_collection") + "?page_size=2",
			**self._auth(),
		)
		data = resp.json()
		self.assertEqual(data["count"], 6)  # includes SMT from setUpTestData
		self.assertEqual(len(data["results"]), 2)
		self.assertIsNotNone(data["pagination"]["next"])

	def test_list_endpoints_have_count(self):
		resp = self.client.get(reverse("api_ticket_collection"), **self._auth())
		data = resp.json()
		self.assertIn("count", data)
		self.assertIn("results", data)
		self.assertIn("pagination", data)
		for key in ("next", "previous"):
			self.assertIn(key, data["pagination"])


@override_settings(TRACKING_API_TOKEN=TOKEN)
class ApiAuthTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.user = User.objects.create_user("bob", password="pw12345!")

	def test_anonymous_is_rejected(self):
		response = self.client.get(reverse("api_meta"))
		self.assertEqual(response.status_code, 401)
		self.assertEqual(response["WWW-Authenticate"], "Bearer")
		self.assertIn("error", response.json())

	def test_valid_bearer_token(self):
		response = self.client.get(
			reverse("api_meta"), HTTP_AUTHORIZATION=f"Bearer {TOKEN}"
		)
		self.assertEqual(response.status_code, 200)

	def test_x_api_token_header(self):
		response = self.client.get(reverse("api_meta"), HTTP_X_API_TOKEN=TOKEN)
		self.assertEqual(response.status_code, 200)

	def test_wrong_token_rejected(self):
		response = self.client.get(
			reverse("api_meta"), HTTP_AUTHORIZATION="Bearer nope"
		)
		self.assertEqual(response.status_code, 401)

	def test_session_auth_works(self):
		self.client.force_login(self.user)
		response = self.client.get(reverse("api_meta"))
		self.assertEqual(response.status_code, 200)


@override_settings(TRACKING_API_TOKEN="")
class ApiTokenDisabledTests(TestCase):
	def test_empty_token_setting_disables_token_auth(self):
		response = self.client.get(
			reverse("api_meta"), HTTP_AUTHORIZATION="Bearer anything"
		)
		self.assertEqual(response.status_code, 401)


@override_settings(TRACKING_API_TOKEN=TOKEN)
class ApiEndpointTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")

	def _auth(self):
		return {"HTTP_AUTHORIZATION": f"Bearer {TOKEN}"}

	def _post(self, url, payload):
		return self.client.post(
			url,
			data=json.dumps(payload),
			content_type="application/json",
			**self._auth(),
		)

	def _patch(self, url, payload):
		return self.client.patch(
			url,
			data=json.dumps(payload),
			content_type="application/json",
			**self._auth(),
		)

	def test_meta_lists_transitions(self):
		response = self.client.get(reverse("api_meta"), **self._auth())
		data = response.json()
		self.assertIn("transitions", data)
		self.assertIn(Ticket.State.OPEN.value, data["transitions"])

	def test_create_project(self):
		response = self._post(
			reverse("api_project_collection"), {"key": "abc", "name": "Alpha"}
		)
		self.assertEqual(response.status_code, 201)
		self.assertEqual(response.json()["key"], "ABC")

	def test_duplicate_project_conflict(self):
		response = self._post(
			reverse("api_project_collection"), {"key": "SMT", "name": "dup"}
		)
		self.assertEqual(response.status_code, 409)

	def test_create_ticket(self):
		response = self._post(
			reverse("api_ticket_collection"),
			{"project": "SMT", "title": "API ticket", "type": "bug", "priority": 4},
		)
		self.assertEqual(response.status_code, 201)
		body = response.json()
		self.assertEqual(body["type"], "bug")
		self.assertEqual(body["allowed_transitions"], ["in_progress", "closed"])

	def test_create_ticket_unknown_project(self):
		response = self._post(
			reverse("api_ticket_collection"), {"project": "NOPE", "title": "x"}
		)
		self.assertEqual(response.status_code, 404)

	def test_ticket_list_filter_by_project(self):
		other = Project.objects.create(key="OTH", name="Other")
		Ticket.objects.create(project=self.project, title="a")
		Ticket.objects.create(project=other, title="b")
		url = reverse("api_ticket_collection") + "?project=SMT"
		response = self.client.get(url, **self._auth())
		titles = [t["title"] for t in response.json()["results"]]
		self.assertEqual(titles, ["a"])

	def test_patch_updates_fields(self):
		ticket = Ticket.objects.create(project=self.project, title="old")
		response = self._patch(
			reverse("api_ticket_detail", args=[ticket.pk]), {"title": "new"}
		)
		self.assertEqual(response.status_code, 200)
		ticket.refresh_from_db()
		self.assertEqual(ticket.title, "new")

	def test_patch_rejects_state(self):
		ticket = Ticket.objects.create(project=self.project, title="t")
		response = self._patch(
			reverse("api_ticket_detail", args=[ticket.pk]), {"state": "closed"}
		)
		self.assertEqual(response.status_code, 400)
		ticket.refresh_from_db()
		self.assertEqual(ticket.state, Ticket.State.OPEN)

	def test_transition_valid(self):
		ticket = Ticket.objects.create(project=self.project, title="t")
		response = self._post(
			reverse("api_ticket_transition", args=[ticket.pk]),
			{"state": "in_progress"},
		)
		self.assertEqual(response.status_code, 200)
		ticket.refresh_from_db()
		self.assertEqual(ticket.state, Ticket.State.IN_PROGRESS)

	def test_transition_illegal_returns_409(self):
		ticket = Ticket.objects.create(project=self.project, title="t")
		response = self._post(
			reverse("api_ticket_transition", args=[ticket.pk]),
			{"state": "resolved"},  # not reachable from open
		)
		self.assertEqual(response.status_code, 409)
		self.assertIn("allowed_transitions", response.json())
		ticket.refresh_from_db()
		self.assertEqual(ticket.state, Ticket.State.OPEN)

	# --- Labels ---------------------------------------------------------------

	def test_create_ticket_with_labels(self):
		label = Label.objects.create(project=self.project, name="urgent", color="red")
		response = self._post(
			reverse("api_ticket_collection"),
			{
				"project": "SMT",
				"title": "labelled ticket",
				"type": "bug",
				"priority": 4,
				"labels": ["urgent"],
			},
		)
		self.assertEqual(response.status_code, 201)
		body = response.json()
		self.assertEqual(len(body["labels"]), 1)
		self.assertEqual(body["labels"][0]["name"], "urgent")
		ticket = Ticket.objects.get(pk=body["id"])
		self.assertIn(label, ticket.labels.all())

	def test_create_ticket_with_unknown_labels_ignored(self):
		response = self._post(
			reverse("api_ticket_collection"),
			{
				"project": "SMT",
				"title": "ticket with unknown label",
				"labels": ["nonexistent"],
			},
		)
		self.assertEqual(response.status_code, 201)
		body = response.json()
		self.assertEqual(len(body["labels"]), 0)

	def test_patch_updates_labels(self):
		label = Label.objects.create(project=self.project, name="blocked", color="orange")
		ticket = Ticket.objects.create(project=self.project, title="t")
		response = self._patch(
			reverse("api_ticket_detail", args=[ticket.pk]),
			{"labels": ["blocked"]},
		)
		self.assertEqual(response.status_code, 200)
		body = response.json()
		self.assertEqual(len(body["labels"]), 1)
		self.assertEqual(body["labels"][0]["name"], "blocked")
		ticket.refresh_from_db()
		self.assertIn(label, ticket.labels.all())

	def test_patch_clears_labels(self):
		label = Label.objects.create(project=self.project, name="urgent", color="red")
		ticket = Ticket.objects.create(project=self.project, title="t")
		ticket.labels.add(label)
		response = self._patch(
			reverse("api_ticket_detail", args=[ticket.pk]),
			{"labels": []},
		)
		self.assertEqual(response.status_code, 200)
		body = response.json()
		self.assertEqual(len(body["labels"]), 0)
		ticket.refresh_from_db()
		self.assertEqual(ticket.labels.count(), 0)

	def test_patch_labels_unknown_label_ignored(self):
		ticket = Ticket.objects.create(project=self.project, title="t")
		response = self._patch(
			reverse("api_ticket_detail", args=[ticket.pk]),
			{"labels": ["nonexistent"]},
		)
		self.assertEqual(response.status_code, 200)
		body = response.json()
		self.assertEqual(len(body["labels"]), 0)
		ticket.refresh_from_db()
		self.assertEqual(ticket.labels.count(), 0)

	# --- Attachments -----------------------------------------------------------

	def _upload_file(self, url, file, params=None):
		return self.client.post(
			url,
			{"file": file, **(params or {})},
			**self._auth(),
		)

	def _get(self, url):
		return self.client.get(url, **self._auth())

	def test_create_ticket_for_attachments(self):
		response = self._post(
			reverse("api_ticket_collection"),
			{"project": "SMT", "title": "ticket with attachments"},
		)
		self.assertEqual(response.status_code, 201)
		return response.json()["id"]

	def test_list_attachments_empty(self):
		ticket_id = self.test_create_ticket_for_attachments()
		response = self._get(
			reverse("api_attachment_collection") + f"?ticket={ticket_id}"
		)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["results"], [])

	def test_upload_png(self):
		ticket_id = self.test_create_ticket_for_attachments()
		img = SimpleUploadedFile("test.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
		response = self._upload_file(
			reverse("api_attachment_collection") + f"?ticket={ticket_id}",
			img,
		)
		self.assertEqual(response.status_code, 201)
		body = response.json()
		self.assertEqual(body["name"], "test.png")
		self.assertEqual(body["mime_type"], "image/png")
		self.assertEqual(body["ticket"], ticket_id)

	def test_upload_jpeg(self):
		ticket_id = self.test_create_ticket_for_attachments()
		img = SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff", content_type="image/jpeg")
		response = self._upload_file(
			reverse("api_attachment_collection") + f"?ticket={ticket_id}",
			img,
		)
		self.assertEqual(response.status_code, 201)
		self.assertEqual(response.json()["mime_type"], "image/jpeg")

	def test_upload_pdf(self):
		ticket_id = self.test_create_ticket_for_attachments()
		pdf = SimpleUploadedFile("doc.pdf", b"%PDF-1.4", content_type="application/pdf")
		response = self._upload_file(
			reverse("api_attachment_collection") + f"?ticket={ticket_id}",
			pdf,
		)
		self.assertEqual(response.status_code, 201)
		self.assertEqual(response.json()["mime_type"], "application/pdf")

	def test_upload_txt(self):
		ticket_id = self.test_create_ticket_for_attachments()
		txt = SimpleUploadedFile("notes.txt", b"hello world", content_type="text/plain")
		response = self._upload_file(
			reverse("api_attachment_collection") + f"?ticket={ticket_id}",
			txt,
		)
		self.assertEqual(response.status_code, 201)
		self.assertEqual(response.json()["mime_type"], "text/plain")

	def test_upload_log(self):
		ticket_id = self.test_create_ticket_for_attachments()
		log = SimpleUploadedFile("app.log", b"log entry", content_type="text/plain")
		response = self._upload_file(
			reverse("api_attachment_collection") + f"?ticket={ticket_id}",
			log,
		)
		self.assertEqual(response.status_code, 201)
		self.assertEqual(response.json()["mime_type"], "text/plain")

	def test_upload_json(self):
		ticket_id = self.test_create_ticket_for_attachments()
		j = SimpleUploadedFile("data.json", b"{}", content_type="application/json")
		response = self._upload_file(
			reverse("api_attachment_collection") + f"?ticket={ticket_id}",
			j,
		)
		self.assertEqual(response.status_code, 201)
		self.assertEqual(response.json()["mime_type"], "application/json")

	def test_upload_rejected_unknown_extension(self):
		ticket_id = self.test_create_ticket_for_attachments()
		zip = SimpleUploadedFile("test.zip", b"PK\x03\x04", content_type="application/zip")
		response = self._upload_file(
			reverse("api_attachment_collection") + f"?ticket={ticket_id}",
			zip,
		)
		self.assertEqual(response.status_code, 400)
		self.assertIn("error", response.json())

	def test_list_attachments_with_files(self):
		ticket_id = self.test_create_ticket_for_attachments()
		img1 = SimpleUploadedFile("a.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
		img2 = SimpleUploadedFile("b.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
		self._upload_file(
			reverse("api_attachment_collection") + f"?ticket={ticket_id}", img1
		)
		self._upload_file(
			reverse("api_attachment_collection") + f"?ticket={ticket_id}", img2
		)
		response = self._get(
			reverse("api_attachment_collection") + f"?ticket={ticket_id}"
		)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(len(response.json()["results"]), 2)

	def test_get_single_attachment(self):
		ticket_id = self.test_create_ticket_for_attachments()
		img = SimpleUploadedFile("test.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
		resp = self._upload_file(
			reverse("api_attachment_collection") + f"?ticket={ticket_id}", img
		)
		attachment_id = resp.json()["id"]
		response = self._get(reverse("api_attachment_detail", args=[attachment_id]))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["name"], "test.png")

	def test_delete_attachment(self):
		ticket_id = self.test_create_ticket_for_attachments()
		img = SimpleUploadedFile("test.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
		resp = self._upload_file(
			reverse("api_attachment_collection") + f"?ticket={ticket_id}", img
		)
		attachment_id = resp.json()["id"]
		response = self.client.delete(
			reverse("api_attachment_detail", args=[attachment_id]),
			**self._auth(),
		)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["status"], "deleted")
		self.assertEqual(Attachment.objects.filter(pk=attachment_id).count(), 0)

	def test_list_attachments_requires_ticket_param(self):
		response = self._get(reverse("api_attachment_collection"))
		self.assertEqual(response.status_code, 400)


@override_settings(TRACKING_API_TOKEN=TOKEN)
class ComponentApiTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.component = Component.objects.create(
			project=cls.project, name="frontend", description="UI layer",
		)

	def _auth(self):
		return {"HTTP_AUTHORIZATION": f"Bearer {TOKEN}"}

	def _post(self, url, payload):
		return self.client.post(
			url, data=json.dumps(payload), content_type="application/json", **self._auth(),
		)

	def _patch(self, url, payload):
		return self.client.patch(
			url, data=json.dumps(payload), content_type="application/json", **self._auth(),
		)

	def test_get_component_detail(self):
		response = self.client.get(
			reverse("api_component_detail", args=[self.component.pk]), **self._auth(),
		)
		self.assertEqual(response.status_code, 200)
		data = response.json()
		self.assertEqual(data["id"], self.component.pk)
		self.assertEqual(data["name"], "frontend")
		self.assertEqual(data["description"], "UI layer")
		self.assertEqual(data["project"], "SMT")

	def test_get_component_detail_not_found(self):
		response = self.client.get(
			reverse("api_component_detail", args=[999]), **self._auth(),
		)
		self.assertEqual(response.status_code, 404)

	def test_patch_component(self):
		response = self._patch(
			reverse("api_component_detail", args=[self.component.pk]),
			{"description": "Frontend UI layer", "name": "frontend-v2"},
		)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["description"], "Frontend UI layer")
		self.assertEqual(response.json()["name"], "frontend-v2")
		self.component.refresh_from_db()
		self.assertEqual(self.component.description, "Frontend UI layer")
		self.assertEqual(self.component.name, "frontend-v2")

	def test_patch_component_partial(self):
		response = self._patch(
			reverse("api_component_detail", args=[self.component.pk]),
			{"description": "Only description"},
		)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["name"], "frontend")

	def test_delete_component(self):
		response = self.client.delete(
			reverse("api_component_detail", args=[self.component.pk]), **self._auth(),
		)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["status"], "deleted")
		self.assertEqual(Component.objects.filter(pk=self.component.pk).count(), 0)

	def test_delete_component_not_found(self):
		response = self.client.delete(
			reverse("api_component_detail", args=[999]), **self._auth(),
		)
		self.assertEqual(response.status_code, 404)



@override_settings(TRACKING_API_TOKEN=TOKEN)
class EpicApiTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.epic = Ticket.objects.create(
			project=cls.project, title="Big Epic", type=Ticket.Type.EPIC
		)
		cls.child = Ticket.objects.create(
			project=cls.project, title="Child Ticket", parent_epic=cls.epic
		)

	def _auth(self):
		return {"HTTP_AUTHORIZATION": f"Bearer {TOKEN}"}

	def _get(self, url):
		return self.client.get(url, **self._auth())

	def _patch(self, url, payload):
		return self.client.patch(
			url, data=json.dumps(payload), content_type="application/json", **self._auth(),
		)

	def test_serialization_includes_parent_epic(self):
		data = self._get(reverse("api_ticket_detail", args=[self.child.pk])).json()
		self.assertEqual(data["parent_epic"], self.epic.pk)
		self.assertEqual(data["parent_epic_display"], "SMT - Big Epic")

	def test_serialization_none_for_orphan(self):
		ticket = Ticket.objects.create(project=self.project, title="Standalone")
		data = self._get(reverse("api_ticket_detail", args=[ticket.pk])).json()
		self.assertIsNone(data["parent_epic"])
		self.assertEqual(data["parent_epic_display"], "")

	def test_patch_parent_epic(self):
		orphan = Ticket.objects.create(project=self.project, title="To assign")
		resp = self._patch(
			reverse("api_ticket_detail", args=[orphan.pk]),
			{"parent_epic": self.epic.pk},
		)
		self.assertEqual(resp.status_code, 200)
		body = resp.json()
		self.assertEqual(body["parent_epic"], self.epic.pk)
		orphan.refresh_from_db()
		self.assertEqual(orphan.parent_epic.pk, self.epic.pk)

	def test_patch_clear_parent_epic(self):
		resp = self._patch(
			reverse("api_ticket_detail", args=[self.child.pk]),
			{"parent_epic": None},
		)
		self.assertEqual(resp.status_code, 200)
		self.child.refresh_from_db()
		self.assertIsNone(self.child.parent_epic)

	def test_list_endpoint_includes_epic(self):
		url = reverse("api_ticket_collection") + "?project=SMT"
		resp = self._get(url)
		tickets = resp.json()["results"]
		ticket_data = {t["id"]: t for t in tickets}
		self.assertEqual(ticket_data[self.child.pk]["parent_epic"], self.epic.pk)
		self.assertEqual(ticket_data[self.epic.pk]["parent_epic"], None)


@override_settings(TRACKING_API_TOKEN=TOKEN)
class ActiveSprintTicketsApiTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")

	def _auth(self):
		return {"HTTP_AUTHORIZATION": f"Bearer {TOKEN}"}

	def _get(self, url):
		return self.client.get(url, **self._auth())

	def test_active_sprint_returns_its_tickets(self):
		sprint = Sprint.objects.create(
			project=self.project, name="Sprint 1", is_active=True
		)
		other = Sprint.objects.create(
			project=self.project, name="Sprint 2", is_active=False
		)
		in_sprint = Ticket.objects.create(
			project=self.project, title="in active", sprint=sprint
		)
		Ticket.objects.create(
			project=self.project, title="in other", sprint=other
		)
		Ticket.objects.create(project=self.project, title="no sprint")

		resp = self._get(
			reverse("api_active_sprint_tickets", args=["SMT"])
		)
		self.assertEqual(resp.status_code, 200)
		body = resp.json()
		self.assertEqual(body["sprint"]["name"], "Sprint 1")
		titles = [t["title"] for t in body["results"]]
		self.assertEqual(titles, ["in active"])
		self.assertEqual(body["results"][0]["id"], in_sprint.pk)

	def test_no_active_sprint_returns_no_tickets(self):
		Sprint.objects.create(
			project=self.project, name="Sprint 1", is_active=False
		)
		Ticket.objects.create(project=self.project, title="a")

		resp = self._get(
			reverse("api_active_sprint_tickets", args=["SMT"])
		)
		self.assertEqual(resp.status_code, 200)
		body = resp.json()
		self.assertIsNone(body["sprint"])
		self.assertEqual(body["results"], [])

	def test_unknown_project_returns_404(self):
		resp = self._get(
			reverse("api_active_sprint_tickets", args=["NOPE"])
		)
		self.assertEqual(resp.status_code, 404)

	def test_requires_auth(self):
		resp = self.client.get(
			reverse("api_active_sprint_tickets", args=["SMT"])
		)
		self.assertEqual(resp.status_code, 401)


@override_settings(TRACKING_API_TOKEN=TOKEN)
class SprintCloseApiTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")

	def _auth(self):
		return {"HTTP_AUTHORIZATION": f"Bearer {TOKEN}"}

	def _post(self, url, payload=None):
		data = json.dumps(payload or {})
		return self.client.post(
			url,
			data=data,
			content_type="application/json",
			**self._auth(),
		)

	def test_close_sprint_default_action_backlog(self):
		sprint = Sprint.objects.create(
			project=self.project, name="Sprint 1", is_active=True,
		)
		ticket = Ticket.objects.create(
			project=self.project, title="sprint ticket", sprint=sprint,
		)
		resp = self._post(
			reverse("api_sprint_close", args=["SMT", sprint.pk])
		)
		self.assertEqual(resp.status_code, 200)
		body = resp.json()
		self.assertFalse(body["is_active"])
		self.assertIsNotNone(body["end_date"])
		sprint.refresh_from_db()
		self.assertFalse(sprint.is_active)
		self.assertIsNotNone(sprint.end_date)
		ticket.refresh_from_db()
		self.assertIsNone(ticket.sprint)

	def test_close_sprint_keep_action(self):
		sprint = Sprint.objects.create(
			project=self.project, name="Sprint 1", is_active=True,
		)
		ticket = Ticket.objects.create(
			project=self.project, title="sprint ticket", sprint=sprint,
		)
		resp = self._post(
			reverse("api_sprint_close", args=["SMT", sprint.pk]),
			{"action": "keep"},
		)
		self.assertEqual(resp.status_code, 200)
		ticket.refresh_from_db()
		self.assertEqual(ticket.sprint, sprint)

	def test_close_sprint_sprint_action(self):
		target_sprint = Sprint.objects.create(
			project=self.project, name="Next Sprint", is_active=True,
		)
		sprint = Sprint.objects.create(
			project=self.project, name="Sprint 1", is_active=True,
		)
		ticket = Ticket.objects.create(
			project=self.project, title="sprint ticket", sprint=sprint,
		)
		resp = self._post(
			reverse("api_sprint_close", args=["SMT", sprint.pk]),
			{"action": "sprint", "target_sprint": target_sprint.pk},
		)
		self.assertEqual(resp.status_code, 200)
		ticket.refresh_from_db()
		self.assertEqual(ticket.sprint, target_sprint)

	def test_close_sprint_sprint_action_no_target_returns_400(self):
		sprint = Sprint.objects.create(
			project=self.project, name="Sprint 1", is_active=True,
		)
		resp = self._post(
			reverse("api_sprint_close", args=["SMT", sprint.pk]),
			{"action": "sprint"},
		)
		self.assertEqual(resp.status_code, 400)

	def test_close_sprint_sprint_action_invalid_target_returns_404(self):
		sprint = Sprint.objects.create(
			project=self.project, name="Sprint 1", is_active=True,
		)
		resp = self._post(
			reverse("api_sprint_close", args=["SMT", sprint.pk]),
			{"action": "sprint", "target_sprint": 999},
		)
		self.assertEqual(resp.status_code, 404)

	def test_close_sprint_sprint_action_same_sprint_returns_400(self):
		sprint = Sprint.objects.create(
			project=self.project, name="Sprint 1", is_active=True,
		)
		resp = self._post(
			reverse("api_sprint_close", args=["SMT", sprint.pk]),
			{"action": "sprint", "target_sprint": sprint.pk},
		)
		self.assertEqual(resp.status_code, 400)

	def test_close_sprint_unknown_project_returns_404(self):
		other_project = Project.objects.create(key="OTH", name="Other")
		sprint = Sprint.objects.create(
			project=other_project, name="Sprint 1", is_active=True,
		)
		resp = self._post(
			reverse("api_sprint_close", args=["NOPE", sprint.pk])
		)
		self.assertEqual(resp.status_code, 404)

	def test_close_sprint_unknown_sprint_returns_404(self):
		resp = self._post(
			reverse("api_sprint_close", args=["SMT", 999])
		)
		self.assertEqual(resp.status_code, 404)

	def test_close_requires_auth(self):
		sprint = Sprint.objects.create(
			project=self.project, name="Sprint 1", is_active=True,
		)
		resp = self.client.post(
			reverse("api_sprint_close", args=["SMT", sprint.pk])
		)
		self.assertEqual(resp.status_code, 401)


@override_settings(TRACKING_API_TOKEN=TOKEN)
class NotificationApiTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_user("alice", password="pw12345!")
		cls.reviewer = User.objects.create_user("bob", password="pw12345!")
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.ticket = Ticket.objects.create(project=cls.project, title="Test ticket")

	def _auth(self):
		return {"HTTP_AUTHORIZATION": f"Bearer {TOKEN}"}

	def test_list_notifications_empty(self):
		self.client.force_login(self.user)
		resp = self.client.get(reverse("api_ticket_collection"))
		data = resp.json()
		# This tests we can call API and get response with expected structure
		self.assertIn("results", data)

	def test_list_notifications_returns_data(self):
		self.client.force_login(self.user)
		Notification.objects.create(
			ticket=self.ticket, recipient=self.user, actor=self.reviewer,
			verb=Notification.Verb.STATE_CHANGED, body="Changed state",
		)
		resp = self.client.get(reverse("api_notification_collection"), **self._auth())
		self.assertEqual(resp.status_code, 200)
		data = resp.json()
		self.assertIn("count", data)
		self.assertIn("pagination", data)
		self.assertIn("results", data)
		self.assertEqual(data["count"], 1)

	def test_list_notifications_unfiltered(self):
		Notification.objects.create(
			ticket=self.ticket, recipient=self.user, actor=self.reviewer,
			verb=Notification.Verb.COMMENTED, read=True,
		)
		self.client.force_login(self.user)
		resp = self.client.get(reverse("api_notification_collection"))
		data = resp.json()
		self.assertEqual(data["count"], 1)
		self.assertEqual(len(data["results"]), 1)

	def test_list_notifications_unread_filter(self):
		self.client.force_login(self.user)
		Notification.objects.create(
			ticket=self.ticket, recipient=self.user, actor=self.reviewer,
			verb=Notification.Verb.COMMENTED, read=False,
		)
		self.client.force_login(self.user)
		resp = self.client.get(reverse("api_notification_collection"))
		data = resp.json()
		self.assertTrue(all(r["read"] is False for r in data["results"]))

	def test_list_notifications_pagination(self):
		self.client.force_login(self.user)
		for i in range(5):
			t = Ticket.objects.create(project=self.project, title=f"Ticket {i}")
			Notification.objects.create(ticket=t, recipient=self.user, actor=self.reviewer, verb=Notification.Verb.COMMENTED)
		self.client.force_login(self.user)
		resp = self.client.get(reverse("api_notification_collection"), {"page_size": "2"})
		data = resp.json()
		self.assertEqual(data["count"], 5)
		self.assertEqual(len(data["results"]), 2)
		self.assertIsNotNone(data["pagination"]["next"])

	def test_mark_single_notification_read(self):
		self.client.force_login(self.user)
		notif = Notification.objects.create(
			ticket=self.ticket, recipient=self.user, actor=self.reviewer,
			verb=Notification.Verb.STATE_CHANGED, read=False,
		)
		resp = self.client.post(
			reverse("api_notification_mark_read", args=[notif.pk]),
		)
		data = resp.json()
		self.assertEqual(data["status"], "read")
		notif.refresh_from_db()
		self.assertTrue(notif.read)

	def test_mark_notification_read_404(self):
		self.client.force_login(self.user)
		resp = self.client.post(
			reverse("api_notification_mark_read", args=[999]),
		)
		self.assertEqual(resp.status_code, 404)

	def test_mark_all_notifications_read(self):
		self.client.force_login(self.user)
		t = Ticket.objects.create(project=self.project, title="Other")
		Notification.objects.create(ticket=self.ticket, recipient=self.user, verb=Notification.Verb.COMMENTED, read=False)
		Notification.objects.create(ticket=t, recipient=self.user, verb=Notification.Verb.STATE_CHANGED, read=False)
		resp = self.client.post(reverse("api_notification_mark_all_read"))
		self.assertEqual(resp.status_code, 200)
		data = resp.json()
		self.assertEqual(data["status"], "all_marked_read")
		self.assertEqual(Notification.objects.filter(recipient=self.user, read=False).count(), 0)

	def test_delete_notification(self):
		self.client.force_login(self.user)
		notif = Notification.objects.create(
			ticket=self.ticket, recipient=self.user, actor=self.reviewer,
			verb=Notification.Verb.COMMENTED,
		)
		resp = self.client.delete(
			reverse("api_notification_delete", args=[notif.pk]),
			**self._auth(),
		)
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(Notification.objects.count(), 0)

	def test_delete_others_notification_404(self):
		self.client.force_login(self.user)
		notif = Notification.objects.create(
			ticket=self.ticket, recipient=self.reviewer, actor=self.reviewer,
			verb=Notification.Verb.COMMENTED,
		)
		resp = self.client.delete(
			reverse("api_notification_delete", args=[notif.pk]),
		)
		self.assertEqual(resp.status_code, 404)

	def test_list_notifications_requires_auth(self):
		resp = self.client.get(reverse("api_notification_collection"))
		self.assertEqual(resp.status_code, 401)


@override_settings(TRACKING_API_TOKEN=TOKEN)
class WatcherApiTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_user("alice", password="pw12345!")
		cls.watcher = User.objects.create_user("bob", password="pw12345!")
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.ticket = Ticket.objects.create(project=cls.project, title="Test ticket")

	def _auth(self):
		return {"HTTP_AUTHORIZATION": f"Bearer {TOKEN}"}

	def test_list_watchers_empty(self):
		resp = self.client.get(reverse("api_watcher_list", args=[self.ticket.pk]), **self._auth())
		self.assertEqual(resp.status_code, 200)
		data = resp.json()
		self.assertEqual(data["count"], 0)

	def test_list_watchers_with_data(self):
		Watcher.objects.create(ticket=self.ticket, user=self.watcher)
		resp = self.client.get(reverse("api_watcher_list", args=[self.ticket.pk]), **self._auth())
		data = resp.json()
		self.assertEqual(data["count"], 1)
		self.assertEqual(len(data["watchers"]), 1)
		self.assertEqual(data["watchers"][0]["username"], "bob")

	def test_add_watcher(self):
		self.client.force_login(self.user)
		resp = self.client.post(
			reverse("api_watcher_list", args=[self.ticket.pk]),
			{"user_id": self.watcher.pk},
		)
		self.assertEqual(resp.status_code, 200)
		data = resp.json()
		self.assertEqual(data["status"], "added")
		self.assertEqual(Watcher.objects.filter(ticket=self.ticket, user=self.watcher).count(), 1)

	def test_add_watcher_already_exists(self):
		self.client.force_login(self.user)
		Watcher.objects.create(ticket=self.ticket, user=self.watcher)
		resp = self.client.post(
			reverse("api_watcher_list", args=[self.ticket.pk]),
			{"user_id": self.watcher.pk},
		)
		data = resp.json()
		self.assertEqual(data["status"], "already_watching")

	def test_add_watcher_invalid_user(self):
		self.client.force_login(self.user)
		resp = self.client.post(
			reverse("api_watcher_list", args=[self.ticket.pk]),
			{"user_id": 9999},
		)
		self.assertEqual(resp.status_code, 400)

	def test_remove_watcher(self):
		w = Watcher.objects.create(ticket=self.ticket, user=self.watcher)
		resp = self.client.delete(
			reverse("api_watcher_remove", args=[self.ticket.pk, self.watcher.pk]),
			**self._auth(),
		)
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(Watcher.objects.count(), 0)

	def test_remove_watcher_404(self):
		resp = self.client.delete(
			reverse("api_watcher_remove", args=[self.ticket.pk, self.watcher.pk]),
			**self._auth(),
		)
		self.assertEqual(resp.status_code, 404)

	def test_workspace_watchers_empty(self):
		self.client.force_login(self.user)
		resp = self.client.get(reverse("api_watcher_workspace_list"))
		self.assertEqual(resp.status_code, 200)
		data = resp.json()
		self.assertEqual(data["count"], 0)

	def test_workspace_watchers_with_data(self):
		self.client.force_login(self.user)
		Watcher.objects.create(ticket=self.ticket, user=self.user)
		resp = self.client.get(reverse("api_watcher_workspace_list"))
		data = resp.json()
		self.assertEqual(data["count"], 1)
		self.assertEqual(len(data["watchers"]), 1)

	def test_add_workspace_watcher(self):
		self.client.force_login(self.user)
		resp = self.client.post(
			reverse("api_watcher_workspace_add"),
			{"ticket_id": self.ticket.pk},
		)
		self.assertEqual(resp.status_code, 200)
		data = resp.json()
		self.assertEqual(data["status"], "added")
		self.assertEqual(Watcher.objects.filter(ticket=self.ticket, user=self.user).count(), 1)

	def test_add_workspace_watcher_invalid_ticket(self):
		self.client.force_login(self.user)
		resp = self.client.post(
			reverse("api_watcher_workspace_add"),
			{"ticket_id": 9999},
		)
		self.assertEqual(resp.status_code, 404)

	def test_remove_workspace_watcher(self):
		self.client.force_login(self.user)
		w = Watcher.objects.create(ticket=self.ticket, user=self.user)
		resp = self.client.delete(
			reverse("api_watcher_workspace_remove", args=[w.pk]),
		)
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(Watcher.objects.count(), 0)

	def test_workspace_watchers_requires_auth(self):
		resp = self.client.get(reverse("api_watcher_workspace_list"))
		self.assertEqual(resp.status_code, 401)


@override_settings(TRACKING_API_TOKEN=TOKEN)
class ApiTicketRelationTests(TestCase):
	"""Covers POST /tickets/<id>/relations/add/ and DELETE /tickets/relations/<pk>/delete/."""

	def setUp(self):
		self.user = User.objects.create_user("relator", password="pw")
		self.project = Project.objects.create(key="REL", name="Relations")
		self.other_project = Project.objects.create(key="OTH", name="Other")
		self.ticket_a = Ticket.objects.create(project=self.project, title="A")
		self.ticket_b = Ticket.objects.create(project=self.project, title="B")
		self.client.force_login(self.user)

	def _add(self, ticket, payload):
		return self.client.post(
			reverse("api_ticket_relation_add", args=[ticket.pk]),
			data=json.dumps(payload),
			content_type="application/json",
		)

	def test_add_relation_returns_201(self):
		resp = self._add(self.ticket_a, {"target_id": self.ticket_b.pk, "type": "blocked_by"})
		self.assertEqual(resp.status_code, 201)
		data = resp.json()
		self.assertEqual(data["type"], "blocked_by")
		self.assertEqual(data["subject"], self.ticket_a.pk)
		self.assertEqual(data["target"], self.ticket_b.pk)
		self.assertTrue(TicketRelation.objects.filter(pk=data["id"]).exists())

	def test_add_relation_creates_symmetric_counterpart(self):
		self._add(self.ticket_a, {"target_id": self.ticket_b.pk, "type": "blocked_by"})
		self.assertTrue(
			TicketRelation.objects.filter(
				subject=self.ticket_b, target=self.ticket_a
			).exists()
		)

	def test_add_relation_missing_target_returns_400(self):
		resp = self._add(self.ticket_a, {"type": "related_to"})
		self.assertEqual(resp.status_code, 400)

	def test_add_relation_unknown_ticket_returns_404(self):
		resp = self.client.post(
			reverse("api_ticket_relation_add", args=[999999]),
			data=json.dumps({"target_id": self.ticket_b.pk}),
			content_type="application/json",
		)
		self.assertEqual(resp.status_code, 404)

	def test_add_relation_unknown_target_returns_404(self):
		resp = self._add(self.ticket_a, {"target_id": 999999})
		self.assertEqual(resp.status_code, 404)

	def test_add_relation_cross_project_returns_400(self):
		foreign = Ticket.objects.create(project=self.other_project, title="F")
		resp = self._add(self.ticket_a, {"target_id": foreign.pk})
		self.assertEqual(resp.status_code, 400)

	def test_add_relation_to_self_returns_400(self):
		resp = self._add(self.ticket_a, {"target_id": self.ticket_a.pk})
		self.assertEqual(resp.status_code, 400)

	def test_add_relation_invalid_type_returns_400(self):
		resp = self._add(self.ticket_a, {"target_id": self.ticket_b.pk, "type": "nope"})
		self.assertEqual(resp.status_code, 400)
		self.assertIn("allowed_types", resp.json())

	def test_add_duplicate_relation_returns_409(self):
		self._add(self.ticket_a, {"target_id": self.ticket_b.pk, "type": "blocked_by"})
		resp = self._add(self.ticket_a, {"target_id": self.ticket_b.pk, "type": "related_to"})
		self.assertEqual(resp.status_code, 409)

	def test_add_relation_requires_auth(self):
		self.client.logout()
		resp = self._add(self.ticket_a, {"target_id": self.ticket_b.pk})
		self.assertEqual(resp.status_code, 401)

	def test_delete_relation_removes_both_directions(self):
		created = self._add(
			self.ticket_a, {"target_id": self.ticket_b.pk, "type": "blocked_by"}
		).json()
		# The symmetric "blocks" counterpart is created on save()
		reverse_rel = TicketRelation.objects.get(
			subject=self.ticket_b,
			target=self.ticket_a,
			relation_type=Ticket._REVERSE_LABELS[Ticket.RelationType.BLOCKED_BY],
		)
		resp = self.client.delete(
			reverse("api_ticket_relation_delete", args=[created["id"]])
		)
		self.assertEqual(resp.status_code, 200)
		self.assertFalse(TicketRelation.objects.filter(pk=created["id"]).exists())
		self.assertFalse(TicketRelation.objects.filter(pk=reverse_rel.pk).exists())
		self.assertEqual(TicketRelation.objects.count(), 0)

	def test_delete_unknown_relation_returns_404(self):
		resp = self.client.delete(
			reverse("api_ticket_relation_delete", args=[999999])
		)
		self.assertEqual(resp.status_code, 404)

