import mistune

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

_markdown = mistune.create_markdown(escape=True)

@register.filter(is_safe=True)
def markdown(value):
	if not value:
		return ""
	return mark_safe(_markdown(str(value)))
