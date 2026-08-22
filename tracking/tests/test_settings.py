"""Tests for the split settings package (base / dev / prod)."""

import os

# prod.py reads SECRET_KEY from the environment at import time.
# Ensure it is available so the prod module can be imported during tests.
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-testing')

from django.test import TestCase


class BaseSettingsTests(TestCase):
    """Verify base.py has every expected setting key."""

    @classmethod
    def setUpClass(cls):
        from setup.settings import base
        cls.base = base
        super().setUpClass()

    def test_base_has_base_dir(self):
        self.assertTrue(hasattr(self.base, 'BASE_DIR'))
        self.assertTrue(self.base.BASE_DIR.is_dir())

    def test_base_has_installed_apps(self):
        self.assertIsInstance(self.base.INSTALLED_APPS, list)
        self.assertIn('tracking', self.base.INSTALLED_APPS)
        self.assertIn('django.contrib.admin', self.base.INSTALLED_APPS)

    def test_base_has_middleware(self):
        self.assertIsInstance(self.base.MIDDLEWARE, list)
        self.assertIn('django.middleware.security.SecurityMiddleware', self.base.MIDDLEWARE)

    def test_base_has_templates(self):
        self.assertIsInstance(self.base.TEMPLATES, list)
        self.assertEqual(len(self.base.TEMPLATES), 1)
        self.assertEqual(self.base.TEMPLATES[0]['BACKEND'],
                         'django.template.backends.django.DjangoTemplates')

    def test_base_has_caches(self):
        self.assertIn('default', self.base.CACHES)

    def test_base_has_i18n(self):
        self.assertEqual(self.base.LANGUAGE_CODE, 'en-us')
        self.assertEqual(self.base.TIME_ZONE, 'UTC')
        self.assertTrue(self.base.USE_I18N)
        self.assertTrue(self.base.USE_TZ)
        self.assertEqual(len(self.base.LANGUAGES), 2)

    def test_base_has_static_media(self):
        self.assertEqual(self.base.STATIC_URL, 'static/')
        self.assertTrue(hasattr(self.base, 'STATICFILES_DIRS'))
        self.assertTrue(hasattr(self.base, 'MEDIA_ROOT'))

    def test_base_has_auth_settings(self):
        self.assertEqual(self.base.LOGIN_URL, 'login')
        self.assertEqual(self.base.LOGIN_REDIRECT_URL, 'dashboard')
        self.assertEqual(self.base.LOGOUT_REDIRECT_URL, 'login')

    def test_base_has_tracking_api_token(self):
        self.assertTrue(hasattr(self.base, 'TRACKING_API_TOKEN'))

    def test_base_has_crispy(self):
        self.assertEqual(self.base.CRISPY_TEMPLATE_PACK, 'bootstrap5')

    def test_base_has_mailers(self):
        self.assertIn('default', self.base.MAILERS)

    def test_base_has_root_urlconf(self):
        self.assertEqual(self.base.ROOT_URLCONF, 'setup.urls')

    def test_base_has_wsgi_application(self):
        self.assertEqual(self.base.WSGI_APPLICATION, 'setup.wsgi.application')

    def test_base_has_auth_password_validators(self):
        self.assertIsInstance(self.base.AUTH_PASSWORD_VALIDATORS, list)
        self.assertEqual(len(self.base.AUTH_PASSWORD_VALIDATORS), 4)


class DevSettingsTests(TestCase):
    """Verify dev.py correctly overrides base settings."""

    @classmethod
    def setUpClass(cls):
        from setup.settings import dev
        cls.dev = dev
        super().setUpClass()

    def test_debug_is_true(self):
        self.assertTrue(self.dev.DEBUG)

    def test_dev_has_sqlite_db(self):
        self.assertIn('default', self.dev.DATABASES)
        self.assertEqual(
            self.dev.DATABASES['default']['ENGINE'],
            'django.db.backends.sqlite3',
        )

    def test_dashboard_cache_timeout_zero(self):
        self.assertEqual(self.dev.DASHBOARD_CACHE_TIMEOUT, 0)

    def test_mailers_console_backend(self):
        self.assertIn(
            'django.core.mail.backends.console.EmailBackend',
            self.dev.MAILERS['default']['BACKEND'],
        )

    def test_inherits_base_apps(self):
        self.assertIn('tracking', self.dev.INSTALLED_APPS)

    def test_inherits_base_middleware(self):
        self.assertIn('django.middleware.security.SecurityMiddleware', self.dev.MIDDLEWARE)


class ProdSettingsTests(TestCase):
    """Verify prod.py reads from environ and applies security settings."""

    @classmethod
    def setUpClass(cls):
        import setup.settings.prod as prod_mod
        cls.prod = prod_mod
        super().setUpClass()

    def test_prod_imports(self):
        self.assertIsNotNone(self.prod)

    def test_debug_defaults_false(self):
        """DEBUG defaults to False in prod (unless overridden via env)."""
        self.assertFalse(self.prod.DEBUG)

    def test_allowed_hosts_from_env(self):
        """ALLOWED_HOSTS should be built from ALLOWED_HOSTS env var in prod."""
        import inspect
        source = inspect.getsource(self.prod)
        self.assertIn('ALLOWED_HOSTS', source)
        self.assertIn('env.list', source)

    def test_database_from_env(self):
        """DATABASES should be built from DATABASE_URL env var in prod."""
        import inspect
        source = inspect.getsource(self.prod)
        self.assertIn('env.db', source)

    def test_sentry_security_headers(self):
        """When DJANGO_SENTRY_DSN is set, security headers are enabled."""
        import inspect
        source = inspect.getsource(self.prod)
        self.assertIn('DJANGO_SENTRY_DSN', source)
        self.assertIn('SECURE_SSL_REDIRECT', source)
        self.assertIn('SECURE_HSTS_SECONDS', source)
        self.assertIn('SECURE_HSTS_INCLUDE_SUBDOMAINS', source)
        self.assertIn('SECURE_HSTS_PRELOAD', source)
        self.assertIn('SESSION_COOKIE_SECURE', source)
        self.assertIn('CSRF_COOKIE_SECURE', source)

    def test_dashboard_cache_timeout_prod(self):
        """DASHBOARD_CACHE_TIMEOUT = 300 in prod."""
        self.assertEqual(self.prod.DASHBOARD_CACHE_TIMEOUT, 300)
