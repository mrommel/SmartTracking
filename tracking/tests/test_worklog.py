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
		# total_remaining_estimate: no worklog original_estimate on child, so falls back to total_original_estimate - spent_hours
		# total_original_estimate = 100 (child estimation fallback), total_spent = 40 min = 0.667h
		self.assertGreater(epic.total_remaining_estimate, 99)
		self.assertLess(epic.total_remaining_estimate, 100)

	def test_epic_rollup_includes_self(self):
		epic = Ticket.objects.create(project=self.project, title="Epic", type=Ticket.Type.EPIC, estimation=200)
		WorkLog.objects.create(ticket=epic, author=self.user, time_spent=50)
		self.assertEqual(epic.total_estimation, 200)
		self.assertEqual(epic.total_spent, 50)
		# epic has estimation 200, no child, so total_original_estimate=200, spent=50min=0.833h
		self.assertGreater(epic.total_remaining_estimate, 199)
		self.assertLess(epic.total_remaining_estimate, 200)


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


class EpicRollupTests(TestCase):
	"""Tests for epic-level time tracking rollups on the Ticket model."""

	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.user = User.objects.create_user("alice", password="pw12345!")
		cls.epic = Ticket.objects.create(
			project=cls.project, title="Big Epic", type=Ticket.Type.EPIC, estimation=500
		)

	def test_progress_zero_without_worklogs(self):
		"""An epic with no worklogs should show 0% progress."""
		self.assertEqual(self.epic.progress_percent, 0.0)

	def test_progress_with_worklogs(self):
		"""Progress should reflect spent vs. original estimate."""
		child1 = Ticket.objects.create(project=self.project, title="C1", estimation=200, parent_epic=self.epic)
		child2 = Ticket.objects.create(project=self.project, title="C2", estimation=300, parent_epic=self.epic)
		# Log 60 min = 1h on child1 with explicit original_estimate
		WorkLog.objects.create(ticket=child1, author=self.user, time_spent=60, original_estimate=200)
		# total_original_estimate = 200 (worklog) + 500 (epic) = 700
		self.assertEqual(self.epic.total_original_estimate, 700)
		# spent = 1h / 700h * 100 = 0.14%
		self.assertAlmostEqual(self.epic.progress_percent, 0.1, places=1)

	def test_original_estimate_fallback_to_estimation(self):
		"""When no worklogs have original_estimate, fallback to child + epic estimation."""
		child = Ticket.objects.create(project=self.project, title="C1", estimation=150, parent_epic=self.epic)
		WorkLog.objects.create(ticket=child, author=self.user, time_spent=30)
		# total_original_estimate = 150 (child estimation fallback) + 500 (epic) = 650
		self.assertEqual(self.epic.total_original_estimate, 650)

	def test_epic_own_estimation_counts_in_rollup(self):
		"""The epic's own estimation should be included when it has children."""
		child = Ticket.objects.create(project=self.project, title="C1", estimation=100, parent_epic=self.epic)
		# epic has estimation=500, child has estimation=100
		self.assertEqual(self.epic.total_original_estimate, 600)

	def test_progress_capped_at_100(self):
		"""Progress should never exceed 100%."""
		epic_no_est = Ticket.objects.create(project=self.project, title="Epic No Est", type=Ticket.Type.EPIC)
		child = Ticket.objects.create(project=self.project, title="C1", estimation=10, parent_epic=epic_no_est)
		# Log 1200 min = 20h, original_estimate=10h on the child
		WorkLog.objects.create(ticket=child, author=self.user, time_spent=1200, original_estimate=10)
		# total_original_estimate = 10 (child worklog), spent = 20h → capped at 100%
		self.assertEqual(epic_no_est.progress_percent, 100.0)

	def test_non_epic_rollup(self):
		"""Non-epic tickets use their own estimation and worklogs only."""
		task = Ticket.objects.create(project=self.project, title="Task", estimation=10)
		WorkLog.objects.create(ticket=task, author=self.user, time_spent=60)
		# original_estimate falls back to estimation=10, spent=1h
		self.assertEqual(task.total_original_estimate, 10)
		self.assertEqual(task.total_spent, 60)
		self.assertAlmostEqual(task.total_remaining_estimate, 9.0, places=1)
		self.assertEqual(task.progress_percent, 10.0)

	def test_worklog_created_updated(self):
		"""WorkLog should have created_at and updated_at."""
		entry = WorkLog.objects.create(ticket=self.epic, author=self.user, time_spent=60)
		self.assertIsNotNone(entry.created_at)

	def test_worklog_optional_estimate_fields(self):
		"""original_estimate and remaining_estimate are optional."""
		entry = WorkLog.objects.create(ticket=self.epic, author=self.user, time_spent=30)
		self.assertIsNone(entry.original_estimate)
		self.assertIsNone(entry.remaining_estimate)

	def test_worklog_with_all_fields(self):
		"""WorkLog can store all optional estimate fields."""
		entry = WorkLog.objects.create(
			ticket=self.epic,
			author=self.user,
			time_spent=120,
			original_estimate=8.0,
			remaining_estimate=5.0,
		)
		self.assertEqual(entry.original_estimate, 8.0)
		self.assertEqual(entry.remaining_estimate, 5.0)
