"""User profile page tests."""

import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import localdate

from tracking.models import Project, Ticket, TicketActivity, Comment, WorkLog, UserProfile

User = get_user_model()


def _png_upload(name="avatar.png", size=None):
	"""A fake PNG upload (content is never decoded, only extension/size)."""
	data = b"\x89PNG" + (b"0" * (size - 4 if size else 128))
	return SimpleUploadedFile(name, data, content_type="image/png")


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


class AvatarUploadTests(TestCase):
	"""Tests for the avatar upload UI on the user profile page."""

	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_user("alice", password="pw12345!")
		cls.other = User.objects.create_user("bob", password="pw12345!")

	def setUp(self):
		self.client.force_login(self.user)

	def test_avatar_card_shown_for_owner(self):
		"""Owners should see the avatar upload form."""
		response = self.client.get(reverse("user_profile", args=[self.user.pk]))
		self.assertContains(response, reverse("user_avatar_update", args=[self.user.pk]))
		self.assertContains(response, "Avatar")

	def test_avatar_card_hidden_for_non_owner(self):
		"""Non-owners should not see the avatar upload form."""
		response = self.client.get(reverse("user_profile", args=[self.other.pk]))
		self.assertNotContains(response, reverse("user_avatar_update", args=[self.other.pk]))

	def test_avatar_update_requires_login(self):
		"""Anonymous users should be redirected to login."""
		self.client.logout()
		response = self.client.post(
			reverse("user_avatar_update", args=[self.user.pk]),
			{"avatar": _png_upload()},
		)
		self.assertEqual(response.status_code, 302)
		self.assertIn("/tracking/login", response.url)

	def test_avatar_upload(self):
		"""Owners should be able to upload an avatar."""
		response = self.client.post(
			reverse("user_avatar_update", args=[self.user.pk]),
			{"avatar": _png_upload()},
		)
		self.assertRedirects(response, reverse("user_profile", args=[self.user.pk]))
		self.user.profile.refresh_from_db()
		self.assertTrue(self.user.profile.avatar)
		self.assertIn("/media/avatars/png/", self.user.profile.avatar.url)

	def test_avatar_upload_replaces_existing(self):
		"""Uploading a second avatar should replace the first."""
		self.client.post(
			reverse("user_avatar_update", args=[self.user.pk]),
			{"avatar": _png_upload("first.png")},
		)
		old_path = self.user.profile.avatar.name
		self.client.post(
			reverse("user_avatar_update", args=[self.user.pk]),
			{"avatar": _png_upload("second.png")},
		)
		self.user.profile.refresh_from_db()
		self.assertNotEqual(self.user.profile.avatar.name, old_path)

	def test_avatar_upload_rejects_bad_extension(self):
		"""Non-image uploads should be rejected."""
		response = self.client.post(
			reverse("user_avatar_update", args=[self.user.pk]),
			{"avatar": SimpleUploadedFile("notes.txt", b"hi")},
		)
		self.assertRedirects(response, reverse("user_profile", args=[self.user.pk]))
		self.assertFalse(UserProfile.objects.filter(user=self.user).exists())

	def test_avatar_upload_rejects_oversize(self):
		"""Images over 5 MB should be rejected."""
		response = self.client.post(
			reverse("user_avatar_update", args=[self.user.pk]),
			{"avatar": _png_upload("big.png", size=5 * 1024 * 1024 + 1)},
		)
		self.assertRedirects(response, reverse("user_profile", args=[self.user.pk]))
		self.assertFalse(UserProfile.objects.filter(user=self.user).exists())

	def test_avatar_upload_forbidden_for_non_owner(self):
		"""Non-owners cannot upload to someone else's profile."""
		self.client.force_login(self.other)
		response = self.client.post(
			reverse("user_avatar_update", args=[self.user.pk]),
			{"avatar": _png_upload()},
		)
		self.assertEqual(response.status_code, 403)
		self.assertFalse(UserProfile.objects.filter(user=self.user).exists())

	def test_avatar_profile_page_shows_upload_after_avatar(self):
		"""The card should show Replace/Remove once an avatar exists."""
		self.client.post(
			reverse("user_avatar_update", args=[self.user.pk]),
			{"avatar": _png_upload()},
		)
		response = self.client.get(reverse("user_profile", args=[self.user.pk]))
		self.assertContains(response, "Replace")
		self.assertContains(response, reverse("user_avatar_delete", args=[self.user.pk]))

	def test_avatar_delete(self):
		"""Owners should be able to remove their avatar."""
		self.client.post(
			reverse("user_avatar_update", args=[self.user.pk]),
			{"avatar": _png_upload()},
		)
		old_path = self.user.profile.avatar.name
		response = self.client.post(
			reverse("user_avatar_delete", args=[self.user.pk])
		)
		self.assertRedirects(response, reverse("user_profile", args=[self.user.pk]))
		self.user.profile.refresh_from_db()
		self.assertFalse(self.user.profile.avatar)
		self.assertFalse(os.path.exists(os.path.join(settings.MEDIA_ROOT, old_path)))

	def test_avatar_delete_forbidden_for_non_owner(self):
		"""Non-owners cannot remove someone else's avatar."""
		self.client.post(
			reverse("user_avatar_update", args=[self.user.pk]),
			{"avatar": _png_upload()},
		)
		self.client.force_login(self.other)
		response = self.client.post(
			reverse("user_avatar_delete", args=[self.user.pk])
		)
		self.assertEqual(response.status_code, 403)
		self.user.profile.refresh_from_db()
		self.assertTrue(self.user.profile.avatar)


class AvatarTagTests(TestCase):
	"""Tests for the avatar_url template tag fallback logic."""

	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_user("alice", password="pw12345!")

	def test_placeholder_without_profile(self):
		"""Users without an uploaded avatar get the UI-Avatars placeholder."""
		from tracking.templatetags.avatar_filters import avatar_url
		url = avatar_url(self.user, 40)
		self.assertIn("ui-avatars.com", url)
		self.assertIn("alice", url)

	def test_uploaded_avatar_takes_precedence(self):
		"""Uploaded avatars are served instead of the placeholder."""
		from tracking.templatetags.avatar_filters import avatar_url
		profile = UserProfile.objects.create(user=self.user)
		profile.avatar.save(
			"alice.png",
			SimpleUploadedFile("alice.png", b"\x89PNG", content_type="image/png"),
		)
		url = avatar_url(self.user, 40)
		self.assertIn("/media/avatars/png/", url)
		self.assertNotIn("ui-avatars.com", url)
