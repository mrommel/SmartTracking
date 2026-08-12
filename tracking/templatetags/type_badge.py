from django import template
from django.utils.safestring import mark_safe

register = template.Library()

_TYPE_VARIANTS = {
	"task": "primary",
	"bug": "danger",
	"story": "info",
	"epic": "warning",
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


@register.simple_tag
def type_badge(ticket, size=None, pill=False):
	raw = _raw_type(ticket)
	variant = _TYPE_VARIANTS.get(raw, "secondary")
	css = ["badge"]
	if variant != "warning":
		css.append(f"text-bg-{variant}")
	else:
		css.append("text-bg-warning text-dark")
	if pill:
		css.append("rounded-pill")
	return mark_safe(f'<span class="{" ".join(css)}">{ticket.get_type_display()}</span>')
