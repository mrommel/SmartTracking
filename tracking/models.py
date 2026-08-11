from django.conf import settings
from django.db import models
from django.db.models import Q
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


class Sprint(models.Model):
	"""A sprint within a project, used as a time-boxed iteration tracker.

	Every project has a special "Backlog" pseudo-sprint (pk=1) that all tickets
	default to.  ``sprint.pk is None`` in the template means "Backlog".
	"""

	project = models.ForeignKey(
		Project,
		on_delete=models.CASCADE,
		related_name="sprints",
		verbose_name=_("project"),
	)
	name = models.CharField(_("name"), max_length=100)
	description = models.TextField(_("description"), blank=True)
	start_date = models.DateField(_("start date"), null=True, blank=True)
	end_date = models.DateField(_("end date"), null=True, blank=True)
	order = models.PositiveIntegerField(_("order"), default=0)
	is_active = models.BooleanField(_("is active"), default=False)
	created_at = models.DateTimeField(_("created at"), auto_now_add=True)

	class Meta:
		verbose_name = _("sprint")
		verbose_name_plural = _("sprints")
		ordering = ["order", "pk"]
		unique_together = ["project", "name"]

	def __str__(self):
		return f"{self.project.key} / {self.name}"

	def save(self, *args, **kwargs):
		super().save(*args, **kwargs)

		# At most one active sprint per project at a time.
		if self.is_active and self.pk is not None:
			Sprint.objects.filter(
				project=self.project,
				is_active=True,
			).exclude(pk=self.pk).update(is_active=False)

	def is_active_sprint(self):
		"""Return True if this sprint is actively active in its project."""
		return self.is_active and Sprint.objects.filter(
			project=self.project, is_active=True, pk=self.pk
		).exists()


class Component(models.Model):
	"""A component within a project, used to group tickets."""

	project = models.ForeignKey(
		Project,
		on_delete=models.CASCADE,
		related_name="components",
		verbose_name=_("project"),
	)
	name = models.CharField(_("name"), max_length=100)
	description = models.TextField(_("description"), blank=True)
	created_at = models.DateTimeField(_("created at"), auto_now_add=True)

	class Meta:
		verbose_name = _("component")
		verbose_name_plural = _("components")
		ordering = ["name"]
		unique_together = ["project", "name"]

	def __str__(self):
		return f"{self.project.key} / {self.name}"


class Label(models.Model):
	"""A label within a project, used to group or highlight tickets."""

	project = models.ForeignKey(
		Project,
		on_delete=models.CASCADE,
		related_name="labels",
		verbose_name=_("project"),
	)
	name = models.CharField(_("name"), max_length=50)
	color = models.CharField(_("color"), max_length=20, default="secondary")
	description = models.TextField(_("description"), blank=True)
	created_at = models.DateTimeField(_("created at"), auto_now_add=True)

	class Meta:
		verbose_name = _("label")
		verbose_name_plural = _("labels")
		ordering = ["name"]
		unique_together = ["project", "name"]

	def __str__(self):
		return f"{self.project.key} / {self.name}"


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
	class RelationType(models.TextChoices):
		RELATED_TO = "related_to", _("Related to")
		BLOCKED_BY = "blocked_by", _("Blocked by")
		TESTED_WITH = "tested_with", _("Found during testing of")
		IS_PARENT = "is_parent", _("Is parent")
		IS_CHILD = "is_child", _("Is child")

	_REVERSE_LABELS = {
		"related_to": "related_to",
		"blocked_by": "blocks",
		"tested_with": "tested_by",
		"is_parent": "is_child",
		"is_child": "is_parent",
	}


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
	estimation = models.IntegerField(
		_("estimation"), null=True, blank=True, default=None
	)
	reporter = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="reported_tickets",
		verbose_name=_("reporter"),
	)
	sprint = models.ForeignKey(
		"Sprint",
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="tickets",
		verbose_name=_("sprint"),
	)
	assignee = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="assigned_tickets",
		verbose_name=_("assignee"),
	)
	components = models.ManyToManyField(
		Component,
		blank=True,
		related_name="tickets",
		verbose_name=_("components"),
	)
	labels = models.ManyToManyField(
		Label,
		blank=True,
		related_name="tickets",
		verbose_name=_("labels"),
	)
	relation_tickets = models.ManyToManyField(
		"self",
		blank=True,
		through="TicketRelation",
		through_fields=("subject", "target"),
		symmetrical=False,
		related_name="related_to",
		verbose_name=_("related tickets"),
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
	def _get_reverse_label(value):
		"""Return the symmetric label for a relation type."""
		return _(_REVERSE_LABELS.get(value, value))

	@property
	def relations(self):
		return TicketRelation.objects.filter(
			Q(subject=self) | Q(target=self)
		).select_related('subject', 'target')

	def available_rels_for(self, scope):
		related = TicketRelation.objects.filter(
			Q(subject=self) | Q(target=self)
		)
		related_pks = set()
		for r in related:
			related_pks.add(r.subject_id)
			related_pks.add(r.target_id)
		related_pks.add(self.pk)
		qs = Ticket.objects.exclude(pk__in=related_pks)
		if scope == 'current_project':
			qs = qs.filter(project=self.project)
		return qs

	def get_relation_label(self, relation):
		if relation.subject_id == self.pk:
			return str(relation.get_relation_type_display())
		return self._get_reverse_label(relation.relation_type)

	def get_other_ticket(self, relation):
		return relation.target if relation.subject_id == self.pk else relation.subject



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


# Allowed file extensions and their MIME types.
_ALLOWED_EXTENSIONS = {
	"png": "image/png",
	"jpg": "image/jpeg",
	"jpeg": "image/jpeg",
	"pdf": "application/pdf",
	"txt": "text/plain",
	"log": "text/plain",
	"json": "application/json",
}
_ALLOWED_MIMES = set(_ALLOWED_EXTENSIONS.values())
_MAX_SIZE = 10 * 1024 * 1024  # 10 MB


def attachment_path(instance, filename):
	ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
	return f"attachments/{instance.ticket.project.key}/{instance.ticket.pk}/{ext}/{filename}"


class Attachment(models.Model):
	"""A file attached to a ticket (images, PDFs, text files, etc.)."""

	ticket = models.ForeignKey(
		Ticket,
		on_delete=models.CASCADE,
		related_name="attachments",
		verbose_name=_("ticket"),
	)
	name = models.CharField(_("name"), max_length=255)
	file = models.FileField(
		_("file"),
		upload_to=attachment_path,
	)
	mime_type = models.CharField(_("mime type"), max_length=100, editable=False)
	created_at = models.DateTimeField(_("created at"), auto_now_add=True)

	class Meta:
		verbose_name = _("attachment")
		verbose_name_plural = _("attachments")
		ordering = ["-created_at"]

	def __str__(self):
		return f"{self.ticket} - {self.name}"

	@property
	def file_extension(self):
		name, ext = self.name.rsplit(".", 1) if "." in self.name else (self.name, "")
		return ext.lower()

	@property
	def is_image(self):
		return self.mime_type.startswith("image/")

	def clean(self):
		# Extract file extension for validation
		if self.name:
			base, ext = self.name.rsplit(".", 1) if "." in self.name else (self.name, "")
		elif hasattr(self.file, "name"):
			base, ext = self.file.name.rsplit(".", 1) if "." in self.file.name else (self.file.name, "")
		else:
			ext = ""
		ext = ext.lower()
		if ext not in _ALLOWED_EXTENSIONS:
			from django.core.exceptions import ValidationError
			raise ValidationError(
				_("File type '.%(ext)s' is not allowed. Allowed: %(allowed)s"),
				params={"ext": ext, "allowed": ", ".join(sorted(_ALLOWED_EXTENSIONS.keys()))},
			)
		if self.mime_type and self.mime_type not in _ALLOWED_MIMES:
			from django.core.exceptions import ValidationError
			raise ValidationError(
				_("MIME type '%(mime)s' is not allowed."),
				params={"mime": self.mime_type},
			)


class TicketRelation(models.Model):
	"""One direction of a symmetric relation between two tickets."""

	subject = models.ForeignKey(
		Ticket,
		on_delete=models.CASCADE,
		related_name="subject_relations",
		verbose_name=_("subject ticket"),
	)
	target = models.ForeignKey(
		Ticket,
		on_delete=models.CASCADE,
		related_name="target_relations",
		verbose_name=_("target ticket"),
	)
	relation_type = models.CharField(
		_("relation type"),
		max_length=20,
		choices=Ticket.RelationType.choices,
	)
	created_at = models.DateTimeField(
		_("created at"), auto_now_add=True, editable=False,
	)
	updated_at = models.DateTimeField(
		_("updated at"), auto_now=True, editable=False,
	)

	class Meta:
		ordering = ["created_at"]
		unique_together = ["subject", "target", "relation_type"]

	def __str__(self):
		return (f"[{self.subject}] {self.get_relation_type_display()} "
				f"{self.target}")

	def save(self, *args, **kwargs):
		"""Create the symmetric counterpart on save."""
		super().save(*args, **kwargs)
		if self.relation_type in Ticket._REVERSE_LABELS:
			TicketRelation.objects.get_or_create(
				subject=self.target,
				target=self.subject,
				relation_type=Ticket._REVERSE_LABELS[self.relation_type],
			)
