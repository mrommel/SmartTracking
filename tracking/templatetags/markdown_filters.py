import hashlib
import mistune

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

from tracking.models import Notification

_markdown = mistune.create_markdown(escape=True)

# Deterministic colour palette derived from hash — kept separate for readability.
_AVATAR_COLORS = (
	"#4e73df", "#1cc88a", "#36b9cc", "#f6c23e", "#e74a3b",
	"#85878f", "#5a5c69", "#fd768e", "#7bdc10", "#0084a7",
)


@register.filter(is_safe=True)
def markdown(value):
	if not value:
		return ""
	return mark_safe(_markdown(str(value)))


@register.filter
def notifications_count(user):
	try:
		return Notification.objects.filter(recipient=user, read=False).count()
	except Exception:
		return 0


@register.filter
def user_initials(user):
	"""Return 2-letter initials from first/last name or username."""
	first = (user.first_name or "").strip()[:1].upper()
	last = (user.last_name or "").strip()[:1].upper()
	if first or last:
		return (first + last)[:2]
	# Fall back to first 2 chars of username
	return (user.username[:2]).upper()


@register.filter
def user_avatar_color(user):
	"""Return a deterministic colour from the user's username hash."""
	h = hashlib.sha256(user.username.encode()).hexdigest()
	idx = int(h[:8], 16) % len(_AVATAR_COLORS)
	return _AVATAR_COLORS[idx]
