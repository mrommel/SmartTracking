"""HTML view tests: login enforcement and the main flows."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from tracking.models import Project, Ticket

User = get_user_model()


class AuthRequiredTests(TestCase):
	"""Every UI page must redirect anonymous users to the login page."""

	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.ticket = Ticket.objects.create(project=cls.project, title="t")

	def test_protected_urls_redirect_to_login(self):
		urls = [
			reverse("dashboard"),
			reverse("project_list"),
			reverse("project_create"),
			reverse("ticket_list"),
			reverse("ticket_create"),
			reverse("ticket_detail", args=[self.ticket.pk]),
		]
		login_url = reverse("login")
		for url in urls:
			with self.subTest(url=url):
				response = self.client.get(url)
				self.assertEqual(response.status_code, 302)
				self.assertIn(login_url, response.url)

	def test_login_page_is_public(self):
		response = self.client.get(reverse("login"))
		self.assertEqual(response.status_code, 200)


class LoggedInFlowTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_user("alice", password="pw12345!")
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")

	def setUp(self):
		self.client.force_login(self.user)

	def test_dashboard_renders(self):
		response = self.client.get(reverse("dashboard"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Dashboard")

	def test_project_create(self):
		response = self.client.post(
			reverse("project_create"),
			{"key": "abc", "name": "Alpha", "description": ""},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		# key is stored uppercased by ProjectForm.clean_key
		self.assertTrue(Project.objects.filter(key="ABC").exists())

	def test_ticket_create_sets_reporter(self):
		response = self.client.post(
			reverse("ticket_create"),
			{
				"project": self.project.pk,
				"title": "New ticket",
				"description": "",
				"type": Ticket.Type.TASK,
				"priority": Ticket.Priority.MEDIUM,
			},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		ticket = Ticket.objects.get(title="New ticket")
		self.assertEqual(ticket.reporter, self.user)

	def test_valid_transition_updates_state(self):
		ticket = Ticket.objects.create(project=self.project, title="t")
		response = self.client.post(
			reverse("ticket_transition", args=[ticket.pk]),
			{"state": Ticket.State.IN_PROGRESS},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		ticket.refresh_from_db()
		self.assertEqual(ticket.state, Ticket.State.IN_PROGRESS)

	def test_invalid_transition_is_rejected(self):
		ticket = Ticket.objects.create(project=self.project, title="t")
		self.client.post(
			reverse("ticket_transition", args=[ticket.pk]),
			{"state": Ticket.State.RESOLVED},  # not reachable from open
		)
		ticket.refresh_from_db()
		self.assertEqual(ticket.state, Ticket.State.OPEN)

