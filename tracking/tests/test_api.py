"""JSON REST API tests: auth layer + endpoint behaviour."""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from tracking.models import Label, Project, Ticket

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
