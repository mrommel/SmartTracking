import mistune

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

from tracking.models import Notification

_markdown = mistune.create_markdown(escape=True)


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
