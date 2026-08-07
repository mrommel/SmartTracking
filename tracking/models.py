from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Project(models.Model):
	"""A container that groups related tickets together."""

	name = models.CharField(_("name"), max_length=200)
	# Short uppercase key used as a prefix for ticket identifiers, e.g. "SMT".
	key = models.SlugField(_("key"), max_length=10, unique=True)
	description = models.TextField(_("description"), blank=True)
	created_at = models.DateTimeField(_("created at"), auto_now_add=True)

	class Meta:
		verbose_name = _("project")
		verbose_name_plural = _("projects")
		ordering = ["key"]

	def __str__(self):
		return f"{self.key} - {self.name}"


class Ticket(models.Model):
	"""A single unit of work (issue/task/bug) that belongs to a project."""

	class Type(models.TextChoices):
		TASK = "task", _("Task")
		BUG = "bug", _("Bug")
		STORY = "story", _("Story")
		EPIC = "epic", _("Epic")

	class State(models.TextChoices):
		OPEN = "open", _("Open")
		IN_PROGRESS = "in_progress", _("In Progress")
		RESOLVED = "resolved", _("Resolved")
		CLOSED = "closed", _("Closed")

	# Allowed simple state transitions (from -> list of reachable states).
	TRANSITIONS = {
		State.OPEN: [State.IN_PROGRESS, State.CLOSED],
		State.IN_PROGRESS: [State.RESOLVED, State.OPEN],
		State.RESOLVED: [State.CLOSED, State.IN_PROGRESS],
		State.CLOSED: [State.OPEN],
	}

	class Priority(models.IntegerChoices):
		LOW = 1, _("Low")
		MEDIUM = 2, _("Medium")
		HIGH = 3, _("High")
		CRITICAL = 4, _("Critical")

	project = models.ForeignKey(
		Project,
		on_delete=models.CASCADE,
		related_name="tickets",
		verbose_name=_("project"),
	)
	title = models.CharField(_("title"), max_length=255)
	description = models.TextField(_("description"), blank=True)
	type = models.CharField(
		_("type"), max_length=20, choices=Type.choices, default=Type.TASK
	)
	state = models.CharField(
		_("state"), max_length=20, choices=State.choices, default=State.OPEN
	)
	priority = models.IntegerField(
		_("priority"), choices=Priority.choices, default=Priority.MEDIUM
	)
	reporter = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="reported_tickets",
		verbose_name=_("reporter"),
	)
	assignee = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="assigned_tickets",
		verbose_name=_("assignee"),
	)
	created_at = models.DateTimeField(_("created at"), auto_now_add=True)
	updated_at = models.DateTimeField(_("updated at"), auto_now=True)

	class Meta:
		verbose_name = _("ticket")
		verbose_name_plural = _("tickets")
		ordering = ["-created_at"]

	def __str__(self):
		return f"[{self.project.key}] {self.title}"

	def allowed_transitions(self):
		"""Return the list of states this ticket can move to next."""
		return self.TRANSITIONS.get(self.State(self.state), [])

	def can_transition_to(self, new_state):
		"""Return True if moving to ``new_state`` is a permitted transition."""
		return self.State(new_state) in self.allowed_transitions()


class Comment(models.Model):
	"""A comment attached to a ticket."""

	ticket = models.ForeignKey(
		Ticket,
		on_delete=models.CASCADE,
		related_name="comments",
		verbose_name=_("ticket"),
	)
	body = models.TextField(_("body"))
	author = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="comments",
		verbose_name=_("author"),
	)
	created_at = models.DateTimeField(_("created at"), auto_now_add=True)
	updated_at = models.DateTimeField(_("updated at"), auto_now=True)

	class Meta:
		verbose_name = _("comment")
		verbose_name_plural = _("comments")
		ordering = ["created_at"]

	def __str__(self):
		return f"Comment on {self.ticket} by {self.author}"
