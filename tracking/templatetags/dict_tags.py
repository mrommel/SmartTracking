from django import template

register = template.Library()


@register.filter(name="getdict")
def getdict(d, key):
	"""Get a value from a dict by key in a template."""
	if d is None:
		return ""
	return d.get(key, "")


@register.filter(name="getint")
def getint(d, key):
	"""Get an integer value from a dict by key in a template."""
	if d is None:
		return 0
	return d.get(key, 0)
