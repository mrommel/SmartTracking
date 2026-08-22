"""
Shared Django settings common to all environments.

Import this from base, then override in dev.py or prod.py.
"""

from pathlib import Path
from django.utils.translation import gettext_lazy as _
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Default SECRET_KEY — used when no env var is set (dev / tests).
# In production, prod.py overrides this via `env("SECRET_KEY")` which
# raises on missing, so this fallback only applies to dev/test.
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    'django-insecure-u2*%zjq-27_w!qf)=(yqj$j0m)l+smh7k+sw#b+!d=-byc5_*p',
)

# Application definition
INSTALLED_APPS = [
	'tracking',
	'dal',
	'dal_select2',
	'liststyle',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
	'django.contrib.humanize',
	# extensions
	'slippers',  # UI components: https://mitchel.me/slippers/docs/installation/
	'django_admin_inline_paginator',
	'django_extensions',
	'crispy_forms',
    'crispy_bootstrap5',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'setup.urls'

WSGI_APPLICATION = 'setup.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates/'],
		'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
				'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
			"builtins": [
				"slippers.templatetags.slippers"
			],
        },
    },
]

# forms styling
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# Authentication
# UI views require login; unauthenticated users are sent to LOGIN_URL.
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Shared bearer token for the JSON REST API (see tracking/api.py). Set via env,
# e.g. `TRACKING_API_TOKEN=... make run`. Empty means token auth is disabled and
# the API only accepts authenticated sessions.
TRACKING_API_TOKEN = os.environ.get("TRACKING_API_TOKEN", "")

# Cache
# https://docs.djangoproject.com/en/6.1/ref/settings/#caches
# LocMemCache for development — uses Django's in-memory cache.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "TIMEOUT": 60,
    }
}

# Dashboard / report stat cache timeout (seconds).
# Used by `@cache_page` on dashboard/report views and `{% cache %}` fragments
# in dashboard, project_detail, reports, and releases templates.
DASHBOARD_CACHE_TIMEOUT = 300

# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

LANGUAGES = [
	('de', _('German')),
	('en', _('English')),
]

LOCALE_PATHS = [BASE_DIR / 'tracking' / 'locale']

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.1/howto/static-files/
STATIC_URL = 'static/'

STATICFILES_DIRS = [
	BASE_DIR / 'tracking' / 'static',
]

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration
MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}
