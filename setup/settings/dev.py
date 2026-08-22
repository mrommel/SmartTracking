"""
Development settings overrides.

Imports shared settings from base.py and applies dev-specific values.
"""

from .base import *  # noqa: F401,F403

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# Database — SQLite for local dev
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Allow all hosts in dev (DEBUG=True bypasses the check anyway)
ALLOWED_HOSTS = ['*']

# Email — console backend writes emails to stdout
MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}

# Disable dashboard/report caching in dev so tests see live data.
DASHBOARD_CACHE_TIMEOUT = 0
