from django import template
from django.utils.safestring import mark_safe

register = template.Library()

_TYPE_VARIANTS = {
	"task": "primary",
	"bug": "danger",
	"story": "info",
	"epic": "warning",
}

_PRIORITY_VARIANTS = {
	"LOW": "secondary",
	"MEDIUM": "info",
	"HIGH": "warning",
	"CRITICAL": "danger",
}


def _raw_type(ticket):
	# Bypass CharField descriptor: the field name "type" conflicts with the
	# inner class "Type" (TextChoices). _saved_get_type_display__ PK  top-level
	# class attribute __dict__ first, falling back to get_type_display()
	#  (slow) resolution.
	raw = ticket.__dict__.get("type")
	if raw:
		return raw
	# Fallback: reverse-map get_type_display to find the key.
	display = ticket.get_type_display()
	from tracking.models import Ticket
	for key, val in Ticket.Type.choices:
		if val == display:
			return key
	return "task"


def _raw_priority(ticket):
	raw = ticket.__dict__.get("priority")
	if raw:
		return raw
	display = ticket.get_priority_display()
	from tracking.models import Ticket
	for key, val in Ticket.Priority.choices:
		if val == display:
			return key
	return "MEDIUM"


@register.simple_tag
def type_badge(ticket, small=False, pill=False):
	raw = _raw_type(ticket)
	variant = _TYPE_VARIANTS.get(raw, "secondary")
	css = ["badge"]
	if variant != "warning":
		css.append(f"text-bg-{variant}")
	else:
		css.append("text-bg-warning text-dark")
	if pill:
		css.append("rounded-pill")
	if small:
		css.append("badge-sm")
	return mark_safe(f'<span class="{" ".join(css)}">{ticket.get_type_display()}</span>')


@register.simple_tag
def priority_badge(ticket, small=False):
	raw_priority = _raw_priority(ticket)
	variant = _PRIORITY_VARIANTS.get(raw_priority, "secondary")
	css = ["badge"]
	if variant != "warning":
		css.append(f"text-bg-{variant}")
	else:
		css.append("text-bg-warning text-dark")
	if small:
		css.append("badge-sm")
	return mark_safe(f'<span class="{" ".join(css)}">{ticket.get_priority_display()}</span>')
