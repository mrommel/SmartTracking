from django import template
import hashlib

from tracking.models import UserProfile

register = template.Library()


def _generate_avatar_url(username, size=40):
	"""Generate a deterministic avatar URL using UI Avatars service.

	The background color is derived from the username hash so each user
	gets a consistent color.
	"""
	h = int(hashlib.sha256(username.encode()).hexdigest()[:6], 16)
	r = (h >> 16) & 0xFF
	g = (h >> 8) & 0xFF
	b = h & 0xFF
	background = f"{r:02X}{g:02X}{b:02X}"
	return f"https://ui-avatars.com/api/?name={username}&size={size}&background={background}&color=fff&bold=true"


@register.simple_tag
def avatar_url(user, size=40):
	"""Return the avatar image URL for a Django User.

	Uses the user's uploaded avatar when present, falling back to the
	deterministic placeholder.
	"""
	try:
		profile = user.profile
	except UserProfile.DoesNotExist:
		profile = None
	if profile and profile.avatar:
		return profile.avatar.url
	return _generate_avatar_url(user.get_username(), size)
