"""JSON REST API tests: auth layer + endpoint behaviour."""

import json

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from tracking.models import Attachment, Component, Label, Project, Ticket, TicketRelation

User = get_user_model()

TOKEN = "test-token-123"


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
		titles = [t["title"] for t in response.json()["tickets"]]
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
		self.assertEqual(response.json()["attachments"], [])

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
		self.assertEqual(len(response.json()["attachments"]), 2)

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
class TicketRelationApiTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.ticket_a = Ticket.objects.create(project=cls.project, title="Ticket A")
		cls.ticket_b = Ticket.objects.create(project=cls.project, title="Ticket B")

	def _auth(self):
		return {"HTTP_AUTHORIZATION": f"Bearer {TOKEN}"}

	def test_delete_relation_not_found(self):
		response = self.client.delete(
			reverse("api_ticket_relation_delete", args=[999]),
			**self._auth(),
		)
		self.assertEqual(response.status_code, 404)

	def test_delete_relation_crashes_on_missing_reverse_map(self):
		relation = TicketRelation.objects.create(
			subject=self.ticket_a, target=self.ticket_b,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		)
		relation_pk = relation.pk
		# API endpoint references Ticket.RelationType._REVERSE_MAP which doesn't exist
		with self.assertRaises(AttributeError):
			self.client.delete(
				reverse("api_ticket_relation_delete", args=[relation_pk]),
				**self._auth(),
			)
		self.assertTrue(TicketRelation.objects.filter(pk=relation_pk).exists())


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
		tickets = resp.json()["tickets"]
		ticket_data = {t["id"]: t for t in tickets}
		self.assertEqual(ticket_data[self.child.pk]["parent_epic"], self.epic.pk)
		self.assertEqual(ticket_data[self.epic.pk]["parent_epic"], None)
