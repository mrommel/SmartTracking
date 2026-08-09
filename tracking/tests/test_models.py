"""Model-level tests, focused on the Ticket state machine and Attachment."""

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile

from tracking.models import Attachment, Project, Ticket


class TicketStateMachineTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")

	def _ticket(self, state=Ticket.State.OPEN):
		return Ticket.objects.create(
			project=self.project, title="t", state=state
		)

	def test_default_state_is_open(self):
		ticket = self._ticket()
		self.assertEqual(ticket.state, Ticket.State.OPEN)

	def test_allowed_transitions_match_map(self):
		ticket = self._ticket(Ticket.State.OPEN)
		self.assertEqual(
			ticket.allowed_transitions(),
			Ticket.TRANSITIONS[Ticket.State.OPEN],
		)

	def test_can_transition_to_allowed(self):
		ticket = self._ticket(Ticket.State.OPEN)
		self.assertTrue(ticket.can_transition_to(Ticket.State.IN_PROGRESS))
		self.assertTrue(ticket.can_transition_to(Ticket.State.CLOSED))

	def test_cannot_transition_to_disallowed(self):
		ticket = self._ticket(Ticket.State.OPEN)
		# open cannot jump straight to resolved
		self.assertFalse(ticket.can_transition_to(Ticket.State.RESOLVED))

	def test_closed_only_reopens(self):
		ticket = self._ticket(Ticket.State.CLOSED)
		self.assertEqual(
			[s for s in ticket.allowed_transitions()],
			[Ticket.State.OPEN],
		)

	def test_str_includes_project_key(self):
		ticket = self._ticket()
		self.assertIn("SMT", str(ticket))


class AttachmentModelTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.ticket = Ticket.objects.create(project=cls.project, title="t")

	def test_attachment_str(self):
		img = SimpleUploadedFile("test.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
		attachment = Attachment.objects.create(
			ticket=self.ticket, name="test.png", file=img, mime_type="image/png"
		)
		self.assertIn("SMT", str(attachment))
		self.assertIn("test.png", str(attachment))

	def test_file_suffix(self):
		img = SimpleUploadedFile("test.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
		attachment = Attachment.objects.create(
			ticket=self.ticket, name="test.png", file=img, mime_type="image/png"
		)
		self.assertEqual(attachment.file_extension, "png")

	def test_is_image(self):
		img = SimpleUploadedFile("test.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
		attachment = Attachment.objects.create(
			ticket=self.ticket, name="test.png", file=img, mime_type="image/png"
		)
		self.assertTrue(attachment.is_image)

	def test_is_not_image(self):
		txt = SimpleUploadedFile("test.txt", b"hello", content_type="text/plain")
		attachment = Attachment.objects.create(
			ticket=self.ticket, name="test.txt", file=txt, mime_type="text/plain"
		)
		self.assertFalse(attachment.is_image)

	def test_allowed_extension_png(self):
		img = SimpleUploadedFile("test.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
		attachment = Attachment.objects.create(
			ticket=self.ticket, name="test.png", file=img, mime_type="image/png"
		)
		attachment.full_clean()  # should not raise

	def test_allowed_extension_jpg(self):
		img = SimpleUploadedFile("test.jpg", b"\xff\xd8\xff", content_type="image/jpeg")
		attachment = Attachment.objects.create(
			ticket=self.ticket, name="test.jpg", file=img, mime_type="image/jpeg"
		)
		attachment.full_clean()

	def test_allowed_extension_pdf(self):
		pdf = SimpleUploadedFile("test.pdf", b"%PDF-1.4", content_type="application/pdf")
		attachment = Attachment.objects.create(
			ticket=self.ticket, name="test.pdf", file=pdf, mime_type="application/pdf"
		)
		attachment.full_clean()

	def test_allowed_extension_txt(self):
		txt = SimpleUploadedFile("test.txt", b"hello", content_type="text/plain")
		attachment = Attachment.objects.create(
			ticket=self.ticket, name="test.txt", file=txt, mime_type="text/plain"
		)
		attachment.full_clean()

	def test_allowed_extension_log(self):
		log = SimpleUploadedFile("test.log", b"log entry", content_type="text/plain")
		attachment = Attachment.objects.create(
			ticket=self.ticket, name="test.log", file=log, mime_type="text/plain"
		)
		attachment.full_clean()

	def test_allowed_extension_json(self):
		j = SimpleUploadedFile("data.json", b"{}", content_type="application/json")
		attachment = Attachment.objects.create(
			ticket=self.ticket, name="data.json", file=j, mime_type="application/json"
		)
		attachment.full_clean()

	def test_invalid_extension_raises(self):
		zip = SimpleUploadedFile("test.zip", b"PK\x03\x04", content_type="application/zip")
		attachment = Attachment.objects.create(
			ticket=self.ticket, name="test.zip", file=zip, mime_type="application/zip"
		)
		with self.assertRaises(ValidationError) as ctx:
			attachment.full_clean()
		self.assertIn("File type", str(ctx.exception))

	def test_ticket_cascade_deletes_attachments(self):
		img = SimpleUploadedFile("test.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
		attachment = Attachment.objects.create(
			ticket=self.ticket, name="test.png", file=img, mime_type="image/png"
		)
		attachment_id = attachment.pk
		self.ticket.delete()
		self.assertEqual(Attachment.objects.filter(pk=attachment_id).count(), 0)

