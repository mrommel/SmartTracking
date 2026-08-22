"""HTML view tests: login enforcement and the main flows."""

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.timezone import localdate

from tracking.forms import SprintForm
from tracking.models import Attachment, Project, Sprint, Ticket, TicketRelation, WorkLog

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


class AttachmentViewTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_user("bob", password="pw12345!")
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.ticket = Ticket.objects.create(project=cls.project, title="t")

	def setUp(self):
		self.client.force_login(self.user)

	def test_ticket_detail_shows_attachments(self):
		img = SimpleUploadedFile("test.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
		Attachment.objects.create(
			ticket=self.ticket, name="test.png", file=img, mime_type="image/png"
		)
		response = self.client.get(reverse("ticket_detail", args=[self.ticket.pk]))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Attachments")
		self.assertContains(response, "test.png")

	def test_ticket_detail_shows_no_attachments(self):
		response = self.client.get(reverse("ticket_detail", args=[self.ticket.pk]))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "No attachments yet")

	def test_upload_attachment(self):
		img = SimpleUploadedFile("test.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
		response = self.client.post(
			reverse("ticket_attachment_upload", args=[self.ticket.pk]),
			{"file": img},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Attachment uploaded")
		self.assertEqual(Attachment.objects.filter(ticket=self.ticket).count(), 1)

	def test_upload_attachment_invalid_extension(self):
		zip = SimpleUploadedFile("test.zip", b"PK\x03\x04", content_type="application/zip")
		response = self.client.post(
			reverse("ticket_attachment_upload", args=[self.ticket.pk]),
			{"file": zip},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(Attachment.objects.filter(ticket=self.ticket).count(), 0)

	def test_delete_attachment(self):
		img = SimpleUploadedFile("test.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
		attachment = Attachment.objects.create(
			ticket=self.ticket, name="test.png", file=img, mime_type="image/png"
		)
		response = self.client.post(
			reverse("ticket_attachment_delete", args=[attachment.pk]),
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Attachment deleted")
		self.assertEqual(Attachment.objects.filter(pk=attachment.pk).count(), 0)

	def test_attachment_serve(self):
		img = SimpleUploadedFile("test.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
		attachment = Attachment.objects.create(
			ticket=self.ticket, name="test.png", file=img, mime_type="image/png"
		)
		response = self.client.get(
			reverse("ticket_attachment_serve", args=[self.ticket.pk, attachment.pk])
		)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response["Content-Type"], "image/png")

	def test_upload_png(self):
		img = SimpleUploadedFile("screenshot.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
		response = self.client.post(
			reverse("ticket_attachment_upload", args=[self.ticket.pk]),
			{"file": img},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		a = Attachment.objects.get(ticket=self.ticket)
		self.assertEqual(a.mime_type, "image/png")

	def test_upload_jpeg(self):
		img = SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff", content_type="image/jpeg")
		response = self.client.post(
			reverse("ticket_attachment_upload", args=[self.ticket.pk]),
			{"file": img},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		a = Attachment.objects.get(ticket=self.ticket)
		self.assertEqual(a.mime_type, "image/jpeg")

	def test_upload_pdf(self):
		pdf = SimpleUploadedFile("doc.pdf", b"%PDF-1.4", content_type="application/pdf")
		response = self.client.post(
			reverse("ticket_attachment_upload", args=[self.ticket.pk]),
			{"file": pdf},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		a = Attachment.objects.get(ticket=self.ticket)
		self.assertEqual(a.mime_type, "application/pdf")

	def test_upload_txt(self):
		txt = SimpleUploadedFile("notes.txt", b"hello word", content_type="text/plain")
		response = self.client.post(
			reverse("ticket_attachment_upload", args=[self.ticket.pk]),
			{"file": txt},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		a = Attachment.objects.get(ticket=self.ticket)
		self.assertEqual(a.mime_type, "text/plain")

	def test_upload_log(self):
		log = SimpleUploadedFile("app.log", b"log entry", content_type="text/plain")
		response = self.client.post(
			reverse("ticket_attachment_upload", args=[self.ticket.pk]),
			{"file": log},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		a = Attachment.objects.get(ticket=self.ticket)
		self.assertEqual(a.mime_type, "text/plain")

	def test_upload_json(self):
		j = SimpleUploadedFile("data.json", b"{}", content_type="application/json")
		response = self.client.post(
			reverse("ticket_attachment_upload", args=[self.ticket.pk]),
			{"file": j},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		a = Attachment.objects.get(ticket=self.ticket)
		self.assertEqual(a.mime_type, "application/json")


class SprintFormTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.sprint = Sprint.objects.create(project=cls.project, name="Sprint 1")

	def test_duplicate_name_rejected(self):
		form = SprintForm(data={
			"name": "Sprint 1",
			"description": "",
			"order": 0,
			"is_active": False,
		}, project=self.project)
		self.assertFalse(form.is_valid())
		self.assertIn("name", form.errors)

	def test_duplicate_name_rejected(self):
		form = SprintForm(data={
			"name": "Sprint 1",
			"description": "",
			"order": 0,
			"is_active": False,
		}, project=self.project)
		self.assertFalse(form.is_valid())
		self.assertIn("name", form.errors)

	def test_same_name_different_project_allowed(self):
		other_project = Project.objects.create(key="OTH", name="Other")
		form = SprintForm(data={
			"name": "Sprint 1",
			"description": "",
			"order": 0,
			"is_active": False,
		}, project=other_project)
		self.assertTrue(form.is_valid())

	def test_update_existing_sprint_same_name_allowed(self):
		form = SprintForm(
			data={
				"name": "Sprint 1",
				"description": "Updated description",
				"order": 1,
				"is_active": False,
			},
			instance=self.sprint,
			project=self.project,
		)
		self.assertTrue(form.is_valid())
		form.save()
		self.sprint.refresh_from_db()
		self.assertEqual(self.sprint.description, "Updated description")

	def test_update_existing_sprint_with_different_name_no_conflict(self):
		Sprint.objects.create(project=self.project, name="Sprint 2")
		form = SprintForm(
			data={
				"name": "Updated Sprint",
				"description": "",
				"order": 1,
				"is_active": False,
			},
			instance=self.sprint,
			project=self.project,
		)
		self.assertTrue(form.is_valid())


class TicketRelationViewTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_user("alice", password="pw12345!")
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.other_project = Project.objects.create(key="OTH", name="Other")
		cls.ticket_a = Ticket.objects.create(project=cls.project, title="Ticket A")
		cls.ticket_b = Ticket.objects.create(project=cls.project, title="Ticket B")
		cls.ticket_other = Ticket.objects.create(project=cls.other_project, title="Other Ticket")

	def setUp(self):
		self.client.force_login(self.user)

	# --- ticket_relation_add ---

	def test_relation_add_success_creates_relation(self):
		response = self.client.post(
			reverse("ticket_relation_add", args=[self.ticket_a.pk]),
			{"target_ticket": self.ticket_b.pk, "relation_type": Ticket.RelationType.BLOCKED_BY},
		)
		self.assertEqual(response.status_code, 302)
		self.assertTrue(TicketRelation.objects.filter(
			subject=self.ticket_a, target=self.ticket_b,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		).exists())

	def test_relation_add_same_project_related_to(self):
		response = self.client.post(
			reverse("ticket_relation_add", args=[self.ticket_a.pk]),
			{"target_ticket": self.ticket_b.pk, "relation_type": Ticket.RelationType.RELATED_TO},
		)
		self.assertEqual(response.status_code, 302)
		self.assertTrue(TicketRelation.objects.filter(
			subject=self.ticket_a, target=self.ticket_b,
			relation_type=Ticket.RelationType.RELATED_TO,
		).exists())

	def test_relation_add_same_project_tested_with(self):
		response = self.client.post(
			reverse("ticket_relation_add", args=[self.ticket_a.pk]),
			{"target_ticket": self.ticket_b.pk, "relation_type": Ticket.RelationType.TESTED_WITH},
		)
		self.assertEqual(response.status_code, 302)
		self.assertTrue(TicketRelation.objects.filter(
			subject=self.ticket_a, target=self.ticket_b,
			relation_type=Ticket.RelationType.TESTED_WITH,
		).exists())

	def test_relation_add_duplicate_rejected(self):
		TicketRelation.objects.create(
			subject=self.ticket_a, target=self.ticket_b,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		)
		response = self.client.post(
			reverse("ticket_relation_add", args=[self.ticket_a.pk]),
			{"target_ticket": self.ticket_b.pk, "relation_type": Ticket.RelationType.BLOCKED_BY},
		)
		self.assertEqual(response.status_code, 302)

	def test_relation_add_reverse_existing_rejected(self):
		TicketRelation.objects.create(
			subject=self.ticket_b, target=self.ticket_a,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		)
		response = self.client.post(
			reverse("ticket_relation_add", args=[self.ticket_a.pk]),
			{"target_ticket": self.ticket_b.pk, "relation_type": Ticket.RelationType.BLOCKED_BY},
		)
		self.assertEqual(response.status_code, 302)

	def test_relation_add_cross_project_rejected(self):
		response = self.client.post(
			reverse("ticket_relation_add", args=[self.ticket_a.pk]),
			{"target_ticket": self.ticket_other.pk, "relation_type": Ticket.RelationType.BLOCKED_BY},
		)
		self.assertEqual(response.status_code, 302)
		self.assertFalse(TicketRelation.objects.filter(
			subject=self.ticket_a, target=self.ticket_other
		).exists())

	def test_relation_add_no_relation_type(self):
		response = self.client.post(
			reverse("ticket_relation_add", args=[self.ticket_a.pk]),
			{"target_ticket": self.ticket_b.pk, "relation_type": ""},
		)
		self.assertEqual(response.status_code, 302)

	def test_relation_add_invalid_target(self):
		response = self.client.post(
			reverse("ticket_relation_add", args=[self.ticket_a.pk]),
			{"target_ticket": 999999, "relation_type": Ticket.RelationType.BLOCKED_BY},
		)
		self.assertEqual(response.status_code, 302)

	def test_relation_delete_get_redirects(self):
		relation = TicketRelation.objects.create(
			subject=self.ticket_a, target=self.ticket_b,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		)
		response = self.client.get(
			reverse("ticket_relation_delete", args=[relation.pk]),
		)
		self.assertEqual(response.status_code, 302)

	def test_relation_delete_removes_relation_and_reverse(self):
		relation = TicketRelation.objects.create(
			subject=self.ticket_a, target=self.ticket_b,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		)
		relation_pk = relation.pk
		# The symmetric "blocks" counterpart is created on save()
		reverse_rel = TicketRelation.objects.get(
			subject=self.ticket_b, target=self.ticket_a,
			relation_type=Ticket._REVERSE_LABELS[Ticket.RelationType.BLOCKED_BY],
		)
		response = self.client.post(
			reverse("ticket_relation_delete", args=[relation_pk]),
		)
		self.assertEqual(response.status_code, 302)
		self.assertFalse(TicketRelation.objects.filter(pk=relation_pk).exists())
		self.assertFalse(TicketRelation.objects.filter(pk=reverse_rel.pk).exists())


class TicketDeleteViewTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_user("alice", password="pw12345!")
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.ticket = Ticket.objects.create(project=cls.project, title="To delete")

		def setUp(self):
			self.client.force_login(self.user)

		def test_ticket_delete_get_shows_confirmation(self):
			response = self.client.get(
				reverse("ticket_delete", args=[self.project.pk, self.ticket.pk])
			)
			self.assertEqual(response.status_code, 200)
			self.assertContains(response, "Are you sure you want to delete")
			self.assertContains(response, "To delete")
			self.assertContains(response, "Delete ticket")
			self.assertContains(response, "Cancel")

		def test_ticket_delete_post_deletes_ticket(self):
			response = self.client.post(
				reverse("ticket_delete", args=[self.project.pk, self.ticket.pk]),
				follow=True,
			)
			self.assertEqual(response.status_code, 200)
			self.assertFalse(Ticket.objects.filter(pk=self.ticket.pk).exists())
			self.assertIn("deleted.", response.content.decode())

		def test_ticket_delete_wrong_project_redirects(self):
			other_project = Project.objects.create(key="OTH", name="Other")
			ticket = Ticket.objects.create(project=other_project, title="Other ticket")
			response = self.client.post(
				reverse("ticket_delete", args=[self.project.pk, ticket.pk]),
				follow=True,
			)
			self.assertEqual(response.status_code, 200)
			self.assertTrue(Ticket.objects.filter(pk=ticket.pk).exists())


class BulkActionTests(TestCase):
	"""Bulk operations on the ticket list."""

	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_user("alice", password="pw12345!")
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.ticket1 = Ticket.objects.create(project=cls.project, title="Ticket 1", state=Ticket.State.OPEN)
		cls.ticket2 = Ticket.objects.create(project=cls.project, title="Ticket 2", state=Ticket.State.OPEN)
		cls.ticket3 = Ticket.objects.create(project=cls.project, title="Ticket 3", state=Ticket.State.OPEN)

	def setUp(self):
		self.client.force_login(self.user)

	# --- ticket_list renders checkboxes and bulk bar ---

	def test_ticket_list_contains_bulk_fields(self):
		response = self.client.get(reverse("ticket_list"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'id="bulk-bar"')
		self.assertContains(response, 'id="select-all"')
		self.assertContains(response, 'bulk-cb"')
		self.assertContains(response, 'id="bulk-action-input"')
		self.assertContains(response, 'id="bulk-ticket-ids"')

	# --- ticket_bulk_action validation ---

	def test_bulk_action_no_tickets(self):
		response = self.client.post(
			reverse("ticket_bulk_action"),
			{"ticket_ids": "", "action": "transition", "state": Ticket.State.IN_PROGRESS},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "No tickets selected")

	def test_bulk_action_invalid_id(self):
		response = self.client.post(
			reverse("ticket_bulk_action"),
			{"ticket_ids": "999999", "action": "transition", "state": Ticket.State.IN_PROGRESS},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Some selected tickets do not exist")

	def test_bulk_action_no_action(self):
		response = self.client.post(
			reverse("ticket_bulk_action"),
			{"ticket_ids": f"{self.ticket1.pk},{self.ticket2.pk}", "action": "", "state": ""},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "No action")

	# --- Bulk transition ---

	def test_bulk_transition_success(self):
		response = self.client.post(
			reverse("ticket_bulk_action"),
			{
				"ticket_ids": f"{self.ticket1.pk},{self.ticket2.pk}",
				"action": "transition",
				"state": Ticket.State.IN_PROGRESS,
			},
		)
		self.assertEqual(response.status_code, 302)
		self.ticket1.refresh_from_db()
		self.ticket2.refresh_from_db()
		self.assertEqual(self.ticket1.state, Ticket.State.IN_PROGRESS)
		self.assertEqual(self.ticket2.state, Ticket.State.IN_PROGRESS)
		self.ticket3.refresh_from_db()
		self.assertEqual(self.ticket3.state, Ticket.State.OPEN)

	def test_bulk_transition_invalid_not_allowed(self):
		# CLOSED can only go to OPEN, not IN_PROGRESS
		self.ticket3.state = Ticket.State.CLOSED
		self.ticket3.save()
		response = self.client.post(
			reverse("ticket_bulk_action"),
			{
				"ticket_ids": f"{self.ticket1.pk},{self.ticket3.pk}",
				"action": "transition",
				"state": Ticket.State.IN_PROGRESS,
			},
		)
		self.assertEqual(response.status_code, 302)
		self.ticket1.refresh_from_db()
		self.ticket3.refresh_from_db()
		self.assertEqual(self.ticket1.state, Ticket.State.OPEN)
		self.assertEqual(self.ticket3.state, Ticket.State.CLOSED)

	def test_bulk_transition_empty_state(self):
		response = self.client.post(
			reverse("ticket_bulk_action"),
			{
				"ticket_ids": f"{self.ticket1.pk},{self.ticket2.pk}",
				"action": "transition",
				"state": "",
			},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		self.ticket1.refresh_from_db()
		self.ticket2.refresh_from_db()
		self.assertEqual(self.ticket1.state, Ticket.State.OPEN)
		self.assertEqual(self.ticket2.state, Ticket.State.OPEN)

	# --- Bulk delete ---

	def test_bulk_delete_success(self):
		response = self.client.post(
			reverse("ticket_bulk_action"),
			{
				"ticket_ids": f"{self.ticket1.pk},{self.ticket2.pk}",
				"action": "delete",
			},
		)
		self.assertEqual(response.status_code, 302)
		self.assertFalse(Ticket.objects.filter(pk=self.ticket1.pk).exists())
		self.assertFalse(Ticket.objects.filter(pk=self.ticket2.pk).exists())
		self.assertTrue(Ticket.objects.filter(pk=self.ticket3.pk).exists())

	# --- Bulk reassign ---

	def test_bulk_reassign_success(self):
		other_user = User.objects.create_user("bob", password="pw12345!")
		response = self.client.post(
			reverse("ticket_bulk_action"),
			{
				"ticket_ids": f"{self.ticket1.pk},{self.ticket2.pk}",
				"action": "reassign",
				"assignee": other_user.pk,
			},
		)
		self.assertEqual(response.status_code, 302)
		self.ticket1.refresh_from_db()
		self.ticket2.refresh_from_db()
		self.assertEqual(self.ticket1.assignee_id, other_user.pk)
		self.assertEqual(self.ticket2.assignee_id, other_user.pk)

	# --- Notes about composition ---

	def test_ticket_list_shows_filter_summary(self):
		response = self.client.get(reverse("ticket_list"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "tickets")


class NotificationViewTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_user("alice", password="pw12345!")
		cls.reviewer = User.objects.create_user("bob", password="pw12345!")
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")

	def setUp(self):
		self.client.force_login(self.user)

	def test_notification_feed_redirects_anonymous(self):
		self.client.logout()
		response = self.client.get(reverse("notification_feed"))
		self.assertEqual(response.status_code, 302)
		self.assertIn("/tracking/login", response.url)

	def test_notification_feed_renders(self):
		response = self.client.get(reverse("notification_feed"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Notifications")

	def test_notification_feed_empty(self):
		response = self.client.get(reverse("notification_feed"))
		self.assertContains(response, "No notifications yet")

	def test_notification_feed_shows_notifications(self):
		from tracking.models import Notification
		ticket = Ticket.objects.create(project=self.project, title="Test ticket")
		Notification.objects.create(
			ticket=ticket,
			recipient=self.user,
			actor=self.reviewer,
			verb=Notification.Verb.STATE_CHANGED,
			body="Status changed",
		)
		response = self.client.get(reverse("notification_feed"))
		self.assertContains(response, "Test ticket")
		self.assertContains(response, "Status changed")

	def test_notification_feed_pagination(self):
		from tracking.models import Notification
		for i in range(60):
			ticket = Ticket.objects.create(project=self.project, title=f"Ticket {i}")
			Notification.objects.create(
				ticket=ticket, recipient=self.user, actor=self.reviewer,
				verb=Notification.Verb.COMMENTED,
			)
		response = self.client.get(reverse("notification_feed"), {"page": 2})
		self.assertEqual(response.status_code, 200)

	def test_notification_mark_read_post(self):
		from tracking.models import Notification
		ticket = Ticket.objects.create(project=self.project, title="Test ticket")
		notif = Notification.objects.create(
			ticket=ticket, recipient=self.user, actor=self.reviewer,
			verb=Notification.Verb.STATE_CHANGED,
			read=False,
		)
		response = self.client.post(
			reverse("notification_mark_read"),
			{"notification_ids": str(notif.pk)},
		)
		self.assertEqual(response.status_code, 302)
		notif.refresh_from_db()
		self.assertTrue(notif.read)

	def test_notification_api_endpoint(self):
		response = self.client.get(reverse("notification_list_api"))
		self.assertEqual(response.status_code, 200)
		data = response.json()
		self.assertIn("results", data)

	def test_notification_api_requires_auth(self):
		self.client.logout()
		response = self.client.get(reverse("notification_list_api"))
		self.assertEqual(response.status_code, 302)
		self.assertIn("/tracking/login", response.url)


class WatcherViewTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_user("alice", password="pw12345!")
		cls.another = User.objects.create_user("bob", password="pw12345!")
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.ticket = Ticket.objects.create(project=cls.project, title="Test ticket")

	def setUp(self):
		self.client.force_login(self.user)

	def test_watcher_manage_redirects_anonymous(self):
		self.client.logout()
		response = self.client.get(reverse("ticket_watchers", args=[self.ticket.pk]))
		self.assertEqual(response.status_code, 302)
		self.assertIn("/tracking/login", response.url)

	def test_watcher_manage_renders(self):
		response = self.client.get(reverse("ticket_watchers", args=[self.ticket.pk]))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Watchers")

	def test_watcher_add(self):
		response = self.client.post(
			reverse("ticket_watchers", args=[self.ticket.pk]),
			{"user": self.another.pk, "ticket_pk": self.ticket.pk},
		)
		self.assertEqual(response.status_code, 302)
		self.assertRedirects(response, reverse("ticket_detail", args=[self.ticket.pk]))
		from tracking.models import Watcher
		self.assertEqual(Watcher.objects.filter(ticket=self.ticket, user=self.another).count(), 1)

	def test_watcher_remove(self):
		from tracking.models import Watcher
		Watcher.objects.create(ticket=self.ticket, user=self.another)
		response = self.client.post(
			reverse("watcher_remove", args=[self.ticket.pk, self.another.pk]),
		)
		self.assertEqual(response.status_code, 302)
		self.assertRedirects(response, reverse("ticket_detail", args=[self.ticket.pk]))
		self.assertEqual(Watcher.objects.filter(ticket=self.ticket, user=self.another).count(), 0)

	def test_watcher_already_exists(self):
		from tracking.models import Watcher
		Watcher.objects.create(ticket=self.ticket, user=self.another)
		response = self.client.post(
			reverse("ticket_watchers", args=[self.ticket.pk]),
			{"user": self.another.pk, "ticket_pk": self.ticket.pk},
		)
		self.assertIn("Already watching", str(response.content))


class WorkLogViewTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.user = User.objects.create_user("bob", password="pw12345!")
		cls.ticket = Ticket.objects.create(project=cls.project, title="t", reporter=cls.user)

	def setUp(self):
		self.client.force_login(self.user)

	def test_create_worklog(self):
		response = self.client.post(
			reverse("ticket_worklog_create", args=[self.ticket.pk]),
			{"form_type": "worklog", "time_spent": 90, "date": localdate(), "comment": "Testing"},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Work logged successfully")
		self.assertEqual(WorkLog.objects.filter(ticket=self.ticket).count(), 1)

	def test_worklog_shown_in_detail(self):
		WorkLog.objects.create(ticket=self.ticket, author=self.user, time_spent=60, date=localdate())
		response = self.client.get(reverse("ticket_detail", args=[self.ticket.pk]))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "60 min")

	def test_delete_own_worklog(self):
		entry = WorkLog.objects.create(ticket=self.ticket, author=self.user, time_spent=60, date=localdate())
		response = self.client.post(
			reverse("worklog_delete", args=[entry.pk]),
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Work log entry deleted")
		self.assertEqual(WorkLog.objects.filter(pk=entry.pk).count(), 0)

	def test_non_author_cannot_delete(self):
		other_user = User.objects.create_user("alice", password="pw12345!")
		entry = WorkLog.objects.create(ticket=self.ticket, author=other_user, time_spent=60, date=localdate())
		response = self.client.post(reverse("worklog_delete", args=[entry.pk]))
		self.assertEqual(response.status_code, 403)

	def test_form_validation_error_shown(self):
		response = self.client.post(
			reverse("ticket_worklog_create", args=[self.ticket.pk]),
			{"form_type": "worklog", "time_spent": -1, "date": localdate()},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		# Should redirect back with error (time_spent must be non-negative)
		self.assertFalse(WorkLog.objects.filter(ticket=self.ticket).exists())


class BuildTicketQuerySetTests(TestCase):
	"""Unit tests for the shared ``build_ticket_queryset`` helper."""

	@classmethod
	def setUpTestData(cls):
		cls.user1 = User.objects.create_user("alice", password="pw12345!")
		cls.user2 = User.objects.create_user("bob", password="pw12345!")
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.other = Project.objects.create(key="OTH", name="Other")
		cls.ticket1 = Ticket.objects.create(
			project=cls.project, title="Fixed Bug", description="has fix",
			state=Ticket.State.CLOSED, priority=Ticket.Priority.HIGH,
			assignee=cls.user2,
		)
		cls.ticket2 = Ticket.objects.create(
			project=cls.project, title="Open Task",
			state=Ticket.State.IN_PROGRESS, priority=Ticket.Priority.LOW,
			assignee=cls.user2,
		)
		cls.ticket3 = Ticket.objects.create(
			project=cls.other, title="Other Project",
			state=Ticket.State.IN_PROGRESS,
			assignee=cls.user2,
		)
		cls.ticket_unassigned = Ticket.objects.create(
			project=cls.project, title="No Assignee",
			state=Ticket.State.OPEN,
			assignee=None,
		)
		cls.ticket_assigned = Ticket.objects.create(
			project=cls.project, title="Assigned to Alice",
			state=Ticket.State.IN_PROGRESS,
			assignee=cls.user1,
		)

	def _make_request(self, params: dict, user=None):
		"""Create a minimal HttpRequest-like object with GET params."""
		from django.test import RequestFactory
		factory = RequestFactory()
		request = factory.get("/", params)
		if user is not None:
			request.user = user
		else:
			request.user = self.user1
		return request

	def _import_helper(self):
		from tracking.queryset_helpers import build_ticket_queryset
		return build_ticket_queryset

	# --- Basic sanity ---------------------------------------------------------

	def test_empty_params_returns_all_project_tickets(self):
		qs = self._import_helper()(self._make_request({}))
		# Should include all tickets in the SMT project (4).
		pks = set(t.pk for t in qs)
		self.assertIn(self.ticket1.pk, pks)
		self.assertIn(self.ticket2.pk, pks)
		self.assertIn(self.ticket_unassigned.pk, pks)
		self.assertIn(self.ticket_assigned.pk, pks)

	def test_state_filter_single(self):
		qs = self._import_helper()(self._make_request({"state": [Ticket.State.OPEN]}))
		self.assertEqual(qs.count(), 1)
		self.assertEqual(qs.first().pk, self.ticket_unassigned.pk)

	def test_state_filter_multi(self):
		qs = self._import_helper()(self._make_request({
			"state": [Ticket.State.OPEN, Ticket.State.CLOSED],
		}))
		self.assertEqual(qs.count(), 2)
		pks = set(t.pk for t in qs)
		self.assertIn(self.ticket1.pk, pks)
		self.assertIn(self.ticket_unassigned.pk, pks)

	def test_project_filter_by_query_param(self):
		qs = self._import_helper()(self._make_request({"project": "SMT"}))
		pks = set(t.pk for t in qs)
		# Excludes tickets from OTH project.
		self.assertNotIn(self.ticket3.pk, pks)
		self.assertIn(self.ticket1.pk, pks)

	def test_project_filter_by_positional_arg(self):
		qs = self._import_helper()(self._make_request({}), project_key="OTH")
		self.assertEqual(qs.count(), 1)
		self.assertEqual(qs.first().pk, self.ticket3.pk)

	# --- Assignee -------------------------------------------------------------

	def test_assignee_me(self):
		qs = self._import_helper()(self._make_request({"assignee": ["me"]}, user=self.user1))
		self.assertEqual(qs.count(), 1)
		self.assertEqual(qs.first().pk, self.ticket_assigned.pk)

	def test_assignee_unassigned(self):
		qs = self._import_helper()(self._make_request({"assignee": ["unassigned"]}))
		self.assertEqual(qs.count(), 1)
		self.assertEqual(qs.first().pk, self.ticket_unassigned.pk)

	def test_assignee_by_id(self):
		qs = self._import_helper()(self._make_request({"assignee": [str(self.user1.pk)]}))
		self.assertEqual(qs.count(), 1)
		self.assertEqual(qs.first().pk, self.ticket_assigned.pk)

	# --- Free-text query ------------------------------------------------------

	def test_query_text_search(self):
		qs = self._import_helper()(self._make_request({"query": "fix"}))
		self.assertEqual(qs.count(), 1)
		self.assertEqual(qs.first().pk, self.ticket1.pk)

	def test_query_id_search(self):
		qs = self._import_helper()(self._make_request({"query": str(self.ticket1.pk)}))
		self.assertGreaterEqual(qs.count(), 1)
		pks = set(t.pk for t in qs)
		self.assertIn(self.ticket1.pk, pks)

	# --- Sorting --------------------------------------------------------------

	def test_sort_created_desc(self):
		qs = self._import_helper()(self._make_request({"sort": "created", "order": "desc"}))
		pks = list(qs.values_list("pk", flat=True))
		# Last item should be the oldest ticket (ticket1).
		self.assertEqual(pks[-1], self.ticket1.pk)

	def test_sort_created_asc(self):
		qs = self._import_helper()(self._make_request({"sort": "created", "order": "asc"}))
		pks = list(qs.values_list("pk", flat=True))
		# First item should be the oldest ticket (ticket1).
		self.assertEqual(pks[0], self.ticket1.pk)

	# --- Performance ----------------------------------------------------------

	def test_select_related_applied(self):
		"""FK accesses should not trigger additional queries."""
		from django.db import connection
		qs = self._import_helper()(self._make_request({}))
		# All FKs are joined; listing should be a single query.
		with self.assertNumQueries(1):
			_ = list(qs)


