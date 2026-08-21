from __future__ import annotations

import re
from typing import TYPE_CHECKING

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Comment, Notification, Ticket, TicketActivity, Watcher

if TYPE_CHECKING:
	from typing import Any

# Pattern to match @username mentions in markdown text.
MENTION_RE = re.compile(r"@([\w.+-]+)", re.IGNORECASE)


def _create_for(ticket: Ticket, recipient, actor, verb: str, body: str = "") -> None:
	"""Create a notification for *recipient* about *ticket* (idempotent)."""
	if not recipient:
		return
	Notification.objects.update_or_create(
		ticket=ticket,
		recipient=recipient,
		verb=verb,
		defaults={"actor": actor, "body": body},
	)


def _deliver_ticket_event(ticket: Ticket, actor, verb: str, body: str = "") -> None:
	"""Deliver a notification about *ticket* to all watchers + reporter."""
	recipients = {w.user for w in ticket.watchers.select_related("user").all()}
	if ticket.reporter:
		recipients.add(ticket.reporter)
	for user in sorted(recipients, key=lambda u: u.get_username()):
		_create_for(ticket, user, actor, verb, body)


def _deliver_mention(ticket: Ticket, actor, mentioned_user) -> None:
	"""Notify a user who was @mentioned in a comment on *ticket*."""
	body = f"{actor.get_username()} mentioned you in {ticket}"
	_create_for(ticket, mentioned_user, actor, Notification.Verb.MENTIONED_IN_COMMENT, body)


@receiver(post_save, sender=TicketActivity)
def handle_ticket_activity(sender, instance: TicketActivity, created: bool, **kwargs: Any):
	if not created:
		return
	ticket = instance.ticket
	actor = instance.actor
	if actor is None:
		return
	match instance.action:
		case TicketActivity.Action.TICKET_CREATED:
			_deliver_ticket_event(ticket, actor, Notification.Verb.ISSUE_ASSIGNED,
				body=f"Ticket created by {actor}")
		case TicketActivity.Action.STATE_CHANGED:
			_deliver_ticket_event(ticket, actor, Notification.Verb.STATE_CHANGED,
				body=f"State changed to {ticket.get_state_display()}")
		case TicketActivity.Action.SPRINT_CHANGED:
			_deliver_ticket_event(ticket, actor, Notification.Verb.STATE_CHANGED,
				body=f"Sprint changed to {instance.new_value}")
		case TicketActivity.Action.TITLE_CHANGED:
			# Also used for assignee changes in the view code.
			if "assignee" in instance.field_name.lower():
				new_val = instance.new_value.split("(", 1)[0].strip() if instance.new_value else ""
				_deliver_ticket_event(ticket, actor, Notification.Verb.ISSUE_ASSIGNED,
					body=f"Assigned to {new_val}")


@receiver(post_save, sender=Comment)
def handle_comment_saved(sender, instance: Comment, created: bool, **kwargs: Any):
	if not created:
		return
	ticket = instance.ticket
	author = instance.author or None

	# Notify watchers and reporter on new comment.
	_deliver_ticket_event(ticket, author, Notification.Verb.COMMENTED,
		body=f"New comment by {author}")

	# Detect @mentions in the comment body.
	bodies = (instance.body or "").strip()
	if bodies and author:
		mentions = MENTION_RE.findall(bodies)
		from django.contrib.auth import get_user_model
		for username in mentions:
			try:
				user = get_user_model().objects.get(username__iexact=username)
				_deliver_mention(ticket, author, user)
			except get_user_model().DoesNotExist:
				pass


def add_watcher(ticket: Ticket, user) -> Watcher:
	"""Add a user as a watcher (no-op if already watching)."""
	return Watcher.objects.get_or_create(ticket=ticket, user=user)


def remove_watcher(ticket: Ticket, user) -> Watcher | None:
	"""Remove a user as a watcher. Returns the deleted watcher or None."""
	try:
		w = Watcher.objects.get(ticket=ticket, user=user)
		w.delete()
		return w
	except Watcher.DoesNotExist:
		return None
