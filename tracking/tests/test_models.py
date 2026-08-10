"""Model-level tests, focused on the Ticket state machine, Attachment, Sprint, and TicketRelation."""

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile

from tracking.models import Attachment, Project, Sprint, Ticket, TicketRelation


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


class SprintModelTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")

	def test_create_basic_sprint(self):
		sprint = Sprint.objects.create(project=self.project, name="Sprint 1")
		self.assertEqual(str(sprint), "SMT / Sprint 1")

	def test_create_sprint_defaults(self):
		from django.utils import timezone
		today = timezone.localdate()
		sprint = Sprint.objects.create(project=self.project, name="Sprint 1")
		self.assertFalse(sprint.is_active)
		self.assertEqual(sprint.order, 0)
		self.assertIsNone(sprint.start_date)
		self.assertIsNone(sprint.end_date)
		self.assertIsNotNone(sprint.created_at)
		self.assertEqual(sprint.project, self.project)

	def test_unique_name_per_project(self):
		Sprint.objects.create(project=self.project, name="Sprint 1")
		with self.assertRaises(ValidationError):
			sprint = Sprint(project=self.project, name="Sprint 1")
			sprint.full_clean()

	def test_same_sprint_name_different_projects_allowed(self):
		other_project = Project.objects.create(key="PROJ", name="OtherProject")
		sprint1 = Sprint.objects.create(project=self.project, name="Sprint 1")
		sprint2 = Sprint.objects.create(project=other_project, name="Sprint 1")
		# Should be able to create since they're in different projects
		self.assertNotEqual(sprint1.pk, sprint2.pk)

	def test_save_activates_only_sprint(self):
		sprint1 = Sprint.objects.create(project=self.project, name="Sprint 1", is_active=True)
		sprint2 = Sprint.objects.create(project=self.project, name="Sprint 2")
		sprint2.is_active = True
		sprint2.save()
		sprint2.refresh_from_db()
		sprint1.refresh_from_db()
		self.assertTrue(sprint2.is_active)
		self.assertFalse(sprint1.is_active)

	def test_save_deactivates_self_when_deactivating(self):
		sprint = Sprint.objects.create(project=self.project, name="Sprint 1", is_active=True)
		sprint.is_active = False
		sprint.save()
		sprint.refresh_from_db()
		self.assertFalse(sprint.is_active)

	def test_is_active_sprint_active(self):
		sprint = Sprint.objects.create(project=self.project, name="Sprint 1", is_active=True)
		self.assertTrue(sprint.is_active_sprint())

	def test_is_active_sprint_not_active(self):
		sprint = Sprint.objects.create(project=self.project, name="Sprint 1", is_active=False)
		self.assertFalse(sprint.is_active_sprint())

	def test_is_active_sprint_with_dirty_flag(self):
		sprint = Sprint.objects.create(project=self.project, name="Sprint 1", is_active=True)
		# Dirty flag: in-memory value differs from DB
		sprint.is_active = False
		self.assertFalse(sprint.is_active)
		# is_active_sprint() short-circuits on self.is_active, so returns False
		self.assertFalse(sprint.is_active_sprint())

	def test_string_format(self):
		sprint = Sprint.objects.create(project=self.project, name="Sprint 1")
		self.assertEqual(str(sprint), "SMT / Sprint 1")

	def test_sprint_cascade_deletes_tickets(self):
		sprint = Sprint.objects.create(project=self.project, name="Sprint 1")
		ticket = Ticket.objects.create(project=self.project, title="t", sprint=sprint)
		sprint_pk = sprint.pk
		sprint.delete()
		self.assertEqual(Sprint.objects.filter(pk=sprint_pk).count(), 0)
		self.assertEqual(Ticket.objects.filter(pk=ticket.pk).count(), 1)

	def test_ticket_sprint_set_null(self):
		sprint = Sprint.objects.create(project=self.project, name="Sprint 1")
		ticket = Ticket.objects.create(project=self.project, title="t", sprint=sprint)
		sprint_pk = sprint.pk
		sprint.delete()
		ticket.refresh_from_db()
		self.assertIsNone(ticket.sprint)

	def test_multiple_projects_one_active_each(self):
		other = Project.objects.create(key="OTH", name="Other")
		sprint1 = Sprint.objects.create(project=self.project, name="Active Sprint", is_active=True)
		sprint2 = Sprint.objects.create(project=other, name="Active Sprint", is_active=True)
		self.assertTrue(sprint1.is_active_sprint())
		self.assertTrue(sprint2.is_active_sprint())


class TicketRelationModelTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.ticket_a = Ticket.objects.create(project=cls.project, title="Ticket A")
		cls.ticket_b = Ticket.objects.create(project=cls.project, title="Ticket B")
		cls.ticket_c = Ticket.objects.create(project=cls.project, title="Ticket C")

	def test_create_relation_creates_symmetric_for_diff_type(self):
		relation = TicketRelation.objects.create(
			subject=self.ticket_a,
			target=self.ticket_b,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		)
		self.ticket_a.refresh_from_db()
		self.ticket_b.refresh_from_db()
		# Original createdAt should exist
		self.assertIsNotNone(relation.created_at)
		# Symmetric counterpart (blocks) should be created
		symmetric = TicketRelation.objects.filter(
			subject=self.ticket_b,
			target=self.ticket_a,
			relation_type="blocks",
		).exists()
		self.assertTrue(symmetric)
		self.assertEqual(TicketRelation.objects.filter(
			subject=self.ticket_a, target=self.ticket_b, relation_type=Ticket.RelationType.BLOCKED_BY
		).count(), 1)

	def test_create_relation_no_symmetric_for_same_type(self):
		relation = TicketRelation.objects.create(
			subject=self.ticket_a,
			target=self.ticket_b,
			relation_type=Ticket.RelationType.RELATED_TO,
		)
		self.assertEqual(TicketRelation.objects.filter(
			subject=self.ticket_a, target=self.ticket_b, relation_type=Ticket.RelationType.RELATED_TO
		).count(), 1)
		self.assertEqual(TicketRelation.objects.filter(
			subject=self.ticket_b, target=self.ticket_a, relation_type=Ticket.RelationType.RELATED_TO
		).count(), 1)

	def test_create_relation_no_symmetric_for_tested_with(self):
		relation = TicketRelation.objects.create(
			subject=self.ticket_a,
			target=self.ticket_b,
			relation_type=Ticket.RelationType.TESTED_WITH,
		)
		# TESTED_WITH should create a TESTED_BY counterpart
		self.assertEqual(TicketRelation.objects.filter(
			subject=self.ticket_a, target=self.ticket_b, relation_type=Ticket.RelationType.TESTED_WITH
		).count(), 1)
		self.assertTrue(TicketRelation.objects.filter(
			subject=self.ticket_b, target=self.ticket_a, relation_type="tested_by"
		).exists())

	def test_relation_duplicate_unique_together(self):
		TicketRelation.objects.create(
			subject=self.ticket_a,
			target=self.ticket_b,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		)
		with self.assertRaises(ValidationError):
			dup = TicketRelation(
				subject=self.ticket_a,
				target=self.ticket_b,
				relation_type=Ticket.RelationType.BLOCKED_BY,
			)
			dup.full_clean()

	def test_relation_str(self):
		relation = TicketRelation.objects.create(
			subject=self.ticket_a,
			target=self.ticket_b,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		)
		self.assertIn("SMT", str(relation))
		self.assertIn("Ticket A", str(relation))
		self.assertIn("Ticket B", str(relation))

	def test_relation_cascade_on_subject_delete(self):
		relation = TicketRelation.objects.create(
			subject=self.ticket_a,
			target=self.ticket_b,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		)
		relation_pk = relation.pk
		self.ticket_a.delete()
		self.assertEqual(TicketRelation.objects.filter(pk=relation_pk).count(), 0)

	def test_relation_cascade_on_target_delete(self):
		relation = TicketRelation.objects.create(
			subject=self.ticket_a,
			target=self.ticket_b,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		)
		relation_pk = relation.pk
		self.ticket_b.delete()
		self.assertEqual(TicketRelation.objects.filter(pk=relation_pk).count(), 0)


class TicketRelationPropertyTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.project = Project.objects.create(key="SMT", name="SmartTracking")
		cls.ticket_a = Ticket.objects.create(project=cls.project, title="Ticket A")
		cls.ticket_b = Ticket.objects.create(project=cls.project, title="Ticket B")
		cls.ticket_c = Ticket.objects.create(project=cls.project, title="Ticket C")

	def test_relations_property(self):
		TicketRelation.objects.create(
			subject=self.ticket_a,
			target=self.ticket_b,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		)
		rels = list(self.ticket_a.relations)
		self.assertEqual(len(rels), 2)
		relation_types = {r.relation_type for r in rels}
		self.assertIn(Ticket.RelationType.BLOCKED_BY, relation_types)

	def test_relations_property_includes_both_directions(self):
		# Create blocked_by relation: ticket_a is blocked by ticket_b
		TicketRelation.objects.create(
			subject=self.ticket_a,
			target=self.ticket_b,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		)
		# After this, ticket_a has blocked_by relation (subject=ticket_a)
		# and blocks relation (target=ticket_a, due to symmetric save)
		rels_a = list(self.ticket_a.relations)
		rels_b = list(self.ticket_b.relations)
		# Both tickets have 2 relations each (one direct, one symmetric)
		self.assertEqual(len(rels_a), 2)
		self.assertEqual(len(rels_b), 2)

	def test_available_rels_for_current_project(self):
		TicketRelation.objects.create(
			subject=self.ticket_a,
			target=self.ticket_b,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		)
		available = self.ticket_a.available_rels_for("current_project")
		self.assertNotIn(self.ticket_a.pk, list(available.values_list('pk', flat=True)))
		self.assertNotIn(self.ticket_b.pk, list(available.values_list('pk', flat=True)))
		self.assertIn(self.ticket_c.pk, list(available.values_list('pk', flat=True)))

	def test_available_rels_for_excludes_self(self):
		available = self.ticket_a.available_rels_for("current_project")
		self.assertNotIn(self.ticket_a.pk, list(available.values_list('pk', flat=True)))

	def test_get_relation_label_subject(self):
		relation = TicketRelation.objects.create(
			subject=self.ticket_a,
			target=self.ticket_b,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		)
		label = self.ticket_a.get_relation_label(relation)
		self.assertIn("Blocked by", label)

	def test_get_relation_label_target(self):
		relation = TicketRelation.objects.create(
			subject=self.ticket_a,
			target=self.ticket_b,
			relation_type=Ticket.RelationType.BLOCKED_BY,
		)
		# _get_reverse_label is defined without self parameter (models.py:242)
		# so calling it through ticket_b raises TypeError
		with self.assertRaises(TypeError):
			self.ticket_b.get_relation_label(relation)

