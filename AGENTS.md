# SmartTracking — AI Agent Guide

Django 6.1 issue/ticket tracker. Single app (`tracking/`) under the `setup/` project. SQLite dev DB, server-rendered Bootstrap 5 templates. No JS framework, no REST API.

## Architecture
- `setup/` is the Django project (settings, root URLconf, WSGI/ASGI). `setup/urls.py` mounts everything under `tracking/` and redirects `/` → `/tracking/dashboard`.
- `tracking/` holds all domain logic. Two models in `tracking/models.py`:
  - `Project` — groups tickets; has a unique uppercase `key` (e.g. `SMT`) used as a ticket-ID prefix.
  - `Ticket` — the work unit. Type/State/Priority are `TextChoices`/`IntegerChoices` enums defined inline.
- **State machine lives in the model, not the view.** `Ticket.TRANSITIONS` maps each `State` to its reachable states; use `ticket.allowed_transitions()` and `ticket.can_transition_to(new_state)` rather than hardcoding state logic. `TicketTransitionForm` builds its choices from `allowed_transitions()` and re-validates via `can_transition_to()` in `clean_state`.
- Views are **function-based** (`tracking/views.py`), thin, and return `render(...)`. State changes go through the dedicated `ticket_transition` POST view + `save(update_fields=["state", "updated_at"])`, never via `TicketForm` (which deliberately omits `state`).
- User feedback uses `django.contrib.messages`; `base.html` renders them as Bootstrap alerts.

## Conventions
- **Indentation is TABS** in Python and templates (see `models.py`, `views.py`). Match the surrounding file — some lines in `settings.py`/`urls.py` are space-indented; don't reformat wholesale.
- Every user-facing model field/label uses `gettext_lazy as _` for i18n (`de` + `en` configured). Wrap new labels in `_(...)`.
- Query performance: use `select_related(...)` for FK access and `annotate(Count(...))` for counts (see `ticket_list`, `project_list`).
- Templates extend `tracking/base.html`; reusable snippets are `_`-prefixed partials pulled in with `{% include %}` and `with` (e.g. `_state_badge.html`). Prefer `{{ ticket.get_<field>_display }}` and `humanize` filters (`naturaltime`).
- URL names are flat (no namespace): reference as `{% url 'ticket_detail' ticket.pk %}` / `redirect("ticket_detail", pk=...)`.
- All pages live in `templates/tracking/` and extend `tracking/base.html` (including `dashboard.html`).

## Workflows (use the Makefile — it pins `python3.12` inside `.venv`)
- Run dev server (loads `.env`, port 8092): `make run`
- Create/apply migrations: `make makemigrations` (note: hardcodes `sqlmigrate tracking 0001` — update the migration number) / `make migrate`
- Translations: `make preparetranslations` then `make compiletranslations` (locale at `tracking/locale/`)
- Rebuild venv: `make clean && make venv`
- Direct manage.py calls must use the venv interpreter: `./.venv/bin/python3.12 manage.py <cmd>`.

## Integrations / gotchas
- `slippers` is registered as a template builtin — its component tags work without `{% load %}`.
- `django-autocomplete-light` (`dal`, `dal_select2`) powers admin `autocomplete_fields` (see `tracking/admin.py`); also `crispy_forms` + `crispy_bootstrap5` (pack = `bootstrap5`), `django_extensions`, `django_admin_inline_paginator`.
- `tracking/tests.py` is empty — there is no test suite yet; run tests with `./.venv/bin/python3.12 manage.py test`.
- Settings are dev-only (`DEBUG=True`, hardcoded `SECRET_KEY`, console email backend). Don't rely on production config.

