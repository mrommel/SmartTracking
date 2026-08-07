"""Tests for the slippers UI components (badge, state_badge)."""

from django.template import engines
from django.test import TestCase

dj = engines["django"]


class _FakeTicket:
	def __init__(self, state):
		self.state = state

	def get_state_display(self):
		return self.state.replace("_", " ").title()


class BadgeComponentTests(TestCase):
	def test_default_variant_is_secondary(self):
		out = dj.from_string("{% #badge %}X{% /badge %}").render({})
		self.assertIn('class="badge text-bg-secondary"', out)
		self.assertIn(">X</span>", out)

	def test_variant_and_pill(self):
		out = dj.from_string(
			"{% #badge variant='primary' pill=True %}9{% /badge %}"
		).render({})
		self.assertIn("text-bg-primary", out)
		self.assertIn("rounded-pill", out)


class StateBadgeComponentTests(TestCase):
	CASES = {
		"open": "text-bg-primary",
		"in_progress": "text-bg-warning",
		"resolved": "text-bg-info",
		"closed": "text-bg-success",
	}

	def test_state_maps_to_variant(self):
		template = dj.from_string("{% state_badge ticket=t %}")
		for state, css in self.CASES.items():
			with self.subTest(state=state):
				out = template.render({"t": _FakeTicket(state)})
				self.assertIn(css, out)

