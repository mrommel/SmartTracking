"""User profile page tests."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import localdate

from tracking.models import Project, Ticket, TicketActivity, Comment, WorkLog

User = get_user_model()


class UserProfileViewTests(TestCase):
	"""Tests for the user profile page at /users/<int:pk>/."""

	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_user("alice", password="pw12345!")
		cls.other = User.objects.create_user("bob", password="pw12345!")
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")

		# Create some tickets assigned to alice
		cls.ticket_assigned = Ticket.objects.create(
			project=cls.project, title="Assigned ticket",
			assignee=cls.user, state=Ticket.State.OPEN,
		)
		cls.ticket_assigned2 = Ticket.objects.create(
			project=cls.project, title="Another assigned ticket",
			assignee=cls.user, state=Ticket.State.IN_PROGRESS,
		)
		# Create a ticket assigned to bob
		cls.ticket_assigned_bob = Ticket.objects.create(
			project=cls.project, title="Bob's ticket",
			assignee=cls.other, state=Ticket.State.CLOSED,
		)

		# Create some tickets reported by alice
		cls.ticket_reported = Ticket.objects.create(
			project=cls.project, title="Reported ticket",
			reporter=cls.user,
		)

		# Create a TicketActivity by alice
		cls.activity = TicketActivity.objects.create(
			ticket=cls.ticket_assigned,
			actor=cls.user,
			action=TicketActivity.Action.STATE_CHANGED,
			field_name="state",
			old_value="open",
			new_value="in_progress",
		)

		# Create a Comment by alice
		cls.comment = Comment.objects.create(
			ticket=cls.ticket_assigned,
			author=cls.user,
			body="This is a comment by alice.",
		)

		# Create a WorkLog by alice
		cls.worklog = WorkLog.objects.create(
			ticket=cls.ticket_assigned,
			author=cls.user,
			time_spent=120,
			date=localdate(),
		)

	def setUp(self):
		self.client.force_login(self.user)

	def test_user_profile_redirects_anonymous(self):
		"""Anonymous users should be redirected to login."""
		self.client.logout()
		response = self.client.get(reverse("user_profile", args=[self.user.pk]))
		self.assertEqual(response.status_code, 302)
		self.assertIn("/tracking/login", response.url)

	def test_user_profile_renders_own(self):
		"""Authenticated users should see their own profile."""
		response = self.client.get(reverse("user_profile", args=[self.user.pk]))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "alice")
		self.assertContains(response, "Assigned tickets")
		self.assertContains(response, "Created tickets")
		self.assertContains(response, "Activity Feed")

	def test_user_profile_renders_others(self):
		"""Authenticated users should see other users' profiles."""
		response = self.client.get(reverse("user_profile", args=[self.other.pk]))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "bob")

	def test_user_profile_shows_assigned_tickets(self):
		"""Profile should show tickets assigned to the user."""
		response = self.client.get(reverse("user_profile", args=[self.user.pk]))
		self.assertContains(response, "Assigned ticket")
		self.assertContains(response, "Another assigned ticket")
		# Should not show bob's ticket
		self.assertNotContains(response, "Bob's ticket")

	def test_user_profile_shows_reported_tickets(self):
		"""Profile should show tickets created by the user."""
		response = self.client.get(reverse("user_profile", args=[self.user.pk]))
		self.assertContains(response, "Reported ticket")

	def test_user_profile_shows_activity(self):
		"""Profile should show the user's activity entries."""
		response = self.client.get(reverse("user_profile", args=[self.user.pk]))
		self.assertContains(response, "State changed")
		self.assertContains(response, "This is a comment by alice.")

	def test_user_profile_stats(self):
		"""Profile should show correct stats."""
		response = self.client.get(reverse("user_profile", args=[self.user.pk]))
		self.assertContains(response, "Assigned tickets")
		self.assertContains(response, "Created tickets")
		self.assertContains(response, "Minutes logged")
		self.assertContains(response, "Comments")

	def test_user_profile_empty(self):
		"""Profile for a user with no data should render gracefully."""
		empty_user = User.objects.create_user("charlie", password="pw12345!")
		response = self.client.get(reverse("user_profile", args=[empty_user.pk]))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "charlie")
		self.assertContains(response, "No assigned tickets")
		self.assertContains(response, "No created tickets")
		self.assertContains(response, "No recent activity")


class UserProfileStatsTests(TestCase):
	"""Tests for stats computation on the user profile page."""

	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_user("alice", password="pw12345!")
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")

		# Create multiple tickets in different states
		for state in Ticket.State:
			Ticket.objects.create(
				project=cls.project,
				title=f"{state.value} ticket",
				assignee=cls.user,
				state=state,
				reporter=cls.user,
			)

		# Create more worklogs
		WorkLog.objects.create(ticket=cls.project.tickets.first(), author=cls.user, time_spent=60, date=localdate())
		WorkLog.objects.create(ticket=cls.project.tickets.first(), author=cls.user, time_spent=30, date=localdate())

		# More comments
		for _ in range(5):
			Comment.objects.create(ticket=cls.project.tickets.first(), author=cls.user, body="comment")

	def setUp(self):
		self.client.force_login(self.user)

	def test_assigned_tickets_count(self):
		"""Should show the correct count of assigned tickets."""
		response = self.client.get(reverse("user_profile", args=[self.user.pk]))
		# We have 4 tickets (one per state) assigned to alice
		self.assertEqual(response.context["assigned_tickets_count"], 4)

	def test_reported_tickets_count(self):
		"""Should show the correct count of reported tickets."""
		response = self.client.get(reverse("user_profile", args=[self.user.pk]))
		# We have 4 tickets (one per state) reported by alice
		self.assertEqual(response.context["reported_tickets_count"], 4)

	def test_total_work_logged(self):
		"""Should show the total minutes logged."""
		response = self.client.get(reverse("user_profile", args=[self.user.pk]))
		self.assertEqual(response.context["total_work_logged"], 90)  # 60 + 30

	def test_comments_count(self):
		"""Should show the correct number of comments."""
		response = self.client.get(reverse("user_profile", args=[self.user.pk]))
		self.assertEqual(response.context["comments_count"], 5)

	def test_assigned_by_state(self):
		"""Should show state breakdown for assigned tickets."""
		response = self.client.get(reverse("user_profile", args=[self.user.pk]))
		by_state = response.context["assigned_by_state"]
		# Should have all 4 states
		self.assertEqual(len(by_state), 4)
		for state in Ticket.State:
			self.assertIn(state.value, by_state)
			label, count = by_state[state.value]
			self.assertEqual(count, 1)

	def test_assigned_tickets_pagination(self):
		"""Should paginate assigned tickets (20/page)."""
		# Create 25 assigned tickets
		for i in range(25):
			Ticket.objects.create(
				project=self.project, title=f"Ticket {i}",
				assignee=self.user,
			)
		response = self.client.get(reverse("user_profile", args=[self.user.pk]))
		self.assertEqual(len(response.context["page_assigned"]), 20)
