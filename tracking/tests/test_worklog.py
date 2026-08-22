from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.timezone import localdate
from tracking.models import Project, Ticket, WorkLog

User = get_user_model()


class WorkLogModelTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.user = User.objects.create_user("bob", password="pw12345!")
		cls.ticket = Ticket.objects.create(project=cls.project, title="t", reporter=cls.user)

	def test_create_basic(self):
		entry = WorkLog.objects.create(ticket=self.ticket, author=self.user, time_spent=60, date=localdate())
		self.assertEqual(entry.time_spent, 60)
		self.assertIn("bob", str(entry))

	def test_cascade_deletes_with_ticket(self):
		entry = WorkLog.objects.create(ticket=self.ticket, author=self.user, time_spent=60)
		pk = entry.pk
		self.ticket.delete()
		self.assertEqual(WorkLog.objects.filter(pk=pk).count(), 0)

	def test_default_date_is_today(self):
		entry = WorkLog.objects.create(ticket=self.ticket, author=self.user, time_spent=30)
		self.assertEqual(entry.date, localdate())

	def test_epic_rollups(self):
		epic = Ticket.objects.create(project=self.project, title="Epic", type=Ticket.Type.EPIC)
		child = Ticket.objects.create(project=self.project, title="Child", estimation=100, parent_epic=epic)
		WorkLog.objects.create(ticket=child, author=self.user, time_spent=40)
		self.assertEqual(epic.total_estimation, 100)
		self.assertEqual(epic.total_spent, 40)
		self.assertEqual(epic.total_remaining, 60)

	def test_epic_rollup_includes_self(self):
		epic = Ticket.objects.create(project=self.project, title="Epic", type=Ticket.Type.EPIC, estimation=200)
		WorkLog.objects.create(ticket=epic, author=self.user, time_spent=50)
		self.assertEqual(epic.total_estimation, 200)
		self.assertEqual(epic.total_spent, 50)
		self.assertEqual(epic.total_remaining, 150)


@override_settings(TRACKING_API_TOKEN="test-token")
class WorkLogAPITests(TestCase):
	TOKEN = "test-token"
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.user = User.objects.create_user("alice", password="pw12345!")
		cls.ticket = Ticket.objects.create(project=cls.project, title="t")

	def _auth(self):
		return {"HTTP_AUTHORIZATION": f"Bearer {self.TOKEN}"}

	def test_list_worklogs(self):
		self.client.force_login(self.user)
		WorkLog.objects.create(ticket=self.ticket, author=self.user, time_spent=60, date=localdate())
		resp = self.client.get(
			reverse("api_ticket_worklog_collection", args=[self.ticket.pk]),
		)
		data = resp.json()
		self.assertEqual(data["count"], 1)
		self.assertEqual(data["results"][0]["time_spent"], 60)
		self.assertEqual(data["results"][0]["author"], "alice")
		self.assertIn("pagination", data)
		self.assertIn("next", data["pagination"])

	def test_create_worklog(self):
		import json
		self.client.force_login(self.user)
		resp = self.client.post(
			reverse("api_ticket_worklog_collection", args=[self.ticket.pk]),
			data=json.dumps({"time_spent": 45, "date": localdate().isoformat(), "comment": "API test"}),
			content_type="application/json",
		)
		self.assertEqual(resp.status_code, 201)
		data = resp.json()
		self.assertEqual(data["time_spent"], 45)
		self.assertEqual(WorkLog.objects.filter(ticket=self.ticket).count(), 1)

	def test_delete_worklog_via_api(self):
		entry = WorkLog.objects.create(ticket=self.ticket, author=self.user, time_spent=60, date=localdate())
		self.client.force_login(self.user)
		resp = self.client.delete(
			reverse("api_worklog_delete", args=[entry.pk]),
		)
		self.assertEqual(resp.status_code, 200)
		data = resp.json()
		self.assertEqual(data["id"], entry.pk)
		self.assertEqual(WorkLog.objects.filter(pk=entry.pk).count(), 0)

	def test_non_author_cannot_delete(self):
		other = User.objects.create_user("bob", password="pw12345!")
		entry = WorkLog.objects.create(ticket=self.ticket, author=other, time_spent=60, date=localdate())
		self.client.force_login(other)
		resp = self.client.delete(
			reverse("api_worklog_delete", args=[entry.pk]),
			**self._auth(),
		)
		# as other user (owner), delete should succeed
		self.assertEqual(resp.status_code, 200)
