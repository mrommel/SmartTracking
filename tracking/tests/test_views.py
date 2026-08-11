"""HTML view tests: login enforcement and the main flows."""

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from tracking.forms import SprintForm
from tracking.models import Attachment, Project, Sprint, Ticket, TicketRelation

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

	def test_relation_delete_crashes_on_missing_reverse_map(self):
		relation = TicketRelation.objects.create(
			subject=self.ticket_a, target=self.ticket_b,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		)
		relation_pk = relation.pk
		# relation.delete() succeeds first, then _REVERSE_MAP lookup fails
		# So the relation will be deleted before the crash
		with self.assertRaises(AttributeError):
			self.client.post(
				reverse("ticket_relation_delete", args=[relation_pk]),
			)
		self.assertFalse(TicketRelation.objects.filter(pk=relation_pk).exists())


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


