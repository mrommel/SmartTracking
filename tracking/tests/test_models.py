"""Model-level tests, focused on the Ticket state machine."""

from django.test import TestCase

from tracking.models import Project, Ticket


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

