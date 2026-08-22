"""
Production settings overrides.

Imports shared settings from base.py and reads sensitive/environmental
settings from environment variables via django-environ.

Set DJANGO_SETTINGS_MODULE=setup.settings.prod before running in production.
"""

import environ
from .base import *  # noqa: F401,F403

env = environ.Env(
    # Read these from the project's .env file (when present)
    env_file=(BASE_DIR.parent / '.env', True),
)

# SECURITY WARNING: read the secret key from an environment variable!
SECRET_KEY = env("SECRET_KEY")

# SECURITY WARNING: default DEBUG=False for production safety.
DEBUG = env.bool("DEBUG", default=False)

# Comma-separated list of allowed hostnames (e.g. example.com,www.example.com).
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# Database — defaults to SQLite on local disk for convenience,
# but any valid Django database URL works (e.g. postgres://...).
DATABASES = {
    'default': env.db(default=f'sqlite:///{BASE_DIR / "db.sqlite3"}'),
}

# Email — console backend by default; override via EMAIL_BACKEND env var.
MAILERS = {
    'default': {
        'BACKEND': env(
            "EMAIL_BACKEND",
            default='django.core.mail.backends.console.EmailBackend',
        ),
    },
}

# Dashboard cache: 5 minutes when DEBUG=False (production-safe default).
DASHBOARD_CACHE_TIMEOUT = 300

# ---------------------------------------------------------------------------
# Production security hardening
# ---------------------------------------------------------------------------

# When DJANGO_SENTRY_DSN is set, the application is running in production.
# Enable strict transport and cookie security headers.
if env("DJANGO_SENTRY_DSN", default=""):

    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # Replace the generic SecurityMiddleware ordering with hardened headers.
    # Insert the additional security middleware after the existing ones.
    _idx = MIDDLEWARE.index('django.middleware.security.SecurityMiddleware')
    MIDDLEWARE.insert(_idx + 1, 'django.middleware.common.BrokenLinkEmailsMiddleware')
