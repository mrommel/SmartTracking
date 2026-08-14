# SmartTracking — AI Agent Guide

Django 6.1 issue/ticket tracker. Single app (`tracking/`) under the `setup/` project. SQLite dev DB, server-rendered Bootstrap 5 templates. No JS framework. A plain-Django JSON REST API (no DRF) lives in `tracking/api.py`, mounted at `/tracking/api/` and exposed as MCP tools.

**Where to find the ticket system:** The MCP server is the primary documentation source. Start it with `make run` (port 8091) and call `get_meta` for all enums (types, states, priorities) and the full state-transition graph. Use the MCP tools (`list_tickets`, `create_ticket`, `transition_ticket`, etc.) to interact — no need to read MD files for ticket domain knowledge. See **Workflows** below to start it.

## Architecture
- `setup/` is the Django project (settings, root URLconf, WSGI/ASGI). `setup/urls.py` mounts everything under `tracking/` and redirects `/` → `/tracking/dashboard`.
- `tracking/` holds all domain logic. Models in `tracking/models.py`:
  - `Project` — groups tickets; has a unique uppercase `key` (e.g. `SMT`) used as a ticket-ID prefix. Owns `Sprint`, `Component`, and `Label` (all project-scoped via `unique_together=["project", "name"]`).
  - `Ticket` — the work unit. Type (`task`/`bug`/`story`/`epic`)/State/Priority are `TextChoices`/`IntegerChoices` enums defined inline. Has `estimation`, `due_date`, `sprint` FK, `parent_epic` self-FK (epics group child tickets via `related_name="child_tickets"`), and `components`/`labels` M2M.
  - `Comment` and `Attachment` — attached to a `Ticket` (comments ordered oldest-first; attachments validate extension/MIME against `_ALLOWED_EXTENSIONS`, 10 MB cap, stored under `media/attachments/<KEY>/<pk>/<ext>/`).
  - `TicketRelation` — a directed link between two tickets (`RelationType`: related_to/blocked_by/tested_with/is_parent/is_child). **Relations are symmetric**: `TicketRelation.save()` auto-creates the reverse counterpart from `Ticket._REVERSE_LABELS`, and deletes must remove both directions (see `ticket_relation_delete`). Only tickets in the *same project* may be related.
- `Sprint` — time-boxed iteration. Every project has a **Backlog pseudo-sprint** (`pk=1`, `name="Backlog"`, `is_backlog` property); tickets with `sprint=None` mean Backlog. At most **one active sprint per project** (enforced in `Sprint.save()`). Close a sprint via `close_with_action(action, target_sprint_id)` where action ∈ `backlog`/`sprint`/`keep` — never delete or clear the backlog sprint.
- **State machine lives in the model, not the view.** `Ticket.TRANSITIONS` maps each `State` to its reachable states; use `ticket.allowed_transitions()` and `ticket.can_transition_to(new_state)` rather than hardcoding state logic. `TicketTransitionForm` builds its choices from `allowed_transitions()` and re-validates via `can_transition_to()` in `clean_state`.
- Views are **function-based** (`tracking/views.py`), thin, and return `render(...)`. State changes go through the dedicated `ticket_transition` POST view + `save(update_fields=["state", "updated_at"])`, never via `TicketForm` (which deliberately omits `state`).
- User feedback uses `django.contrib.messages`; `base.html` renders them as Bootstrap alerts.

## Conventions
- **Indentation is TABS** in Python and templates (see `models.py`, `views.py`). Match the surrounding file — some lines in `settings.py`/`urls.py` are space-indented; don't reformat wholesale.
- Every user-facing model field/label uses `gettext_lazy as _` for i18n (`de` + `en` configured). Wrap new labels in `_(...)`.
- Query performance: use `select_related(...)` for FK access and `annotate(Count(...))` for counts (see `ticket_list`, `project_list`).
- Templates extend `tracking/base.html`; reusable snippets are `_`-prefixed partials pulled in with `{% include %}` and `with` (e.g. `_state_badge.html`). Prefer `{{ ticket.get_<field>_display }}` and `humanize` filters (`naturaltime`).
- Custom template tags in `tracking/templatetags/`: `{% type_badge ticket %}` / `{% priority_badge ticket %}` (`type_badge.py`, Bootstrap `text-bg-*` variants) and the `markdown` filter (`markdown_filters.py`, `mistune` with `escape=True`) for rendering ticket/comment bodies — `{% load %}` them where used.
- URL names are flat (no namespace): reference as `{% url 'ticket_detail' ticket.pk %}` / `redirect("ticket_detail", pk=...)`.
- All pages live in `templates/tracking/` and extend `tracking/base.html` (including `dashboard.html`).

## Workflows (use the Makefile — it pins `python3.12` inside `.venv`)
- Run dev server (loads `.env`, port 8092) **and the bundled MCP server (port 8091)**: `make run`
- Create/apply migrations: `make makemigrations` (note: hardcodes `sqlmigrate tracking 0001` — update the migration number) / `make migrate`
- Translations: `make preparetranslations` then `make compiletranslations` (locale at `tracking/locale/`)
- Rebuild venv: `make clean && make venv`
- Direct manage.py calls must use the venv interpreter: `./.venv/bin/python3.12 manage.py <cmd>`.

## Integrations / gotchas
- `slippers` is registered as a template builtin — its component tags work without `{% load %}`. Reusable UI components are registered in `tracking/templates/components.yaml` and live in `tracking/templates/tracking/components/`: `badge` (props `variant`, `pill`; use as block `{% #badge variant="primary" %}…{% /badge %}`) and `state_badge` (prop `ticket`, maps state→variant). **Never put Django tag syntax (`{% %}`) inside `{# #}` comments in `.html` or `components.yaml`** — multiline `{# #}` isn't supported and the tags get parsed for real (caused component self-recursion).
- `django-autocomplete-light` (`dal`, `dal_select2`) powers admin `autocomplete_fields` (see `tracking/admin.py`); also `crispy_forms` + `crispy_bootstrap5` (pack = `bootstrap5`), `django_extensions`, `django_admin_inline_paginator`, and `mistune` (markdown rendering). Deps are pinned in `requirements.txt` (`mcp`/`httpx` back the bundled MCP server).
- Env vars load from `.env` via `make run` (copy `.env.example`). `TRACKING_API_TOKEN` is the only app var. `.env` is gitignored; `.env.example` is the tracked template.
- Tests live in the `tracking/tests/` package (`test_models.py`, `test_views.py`, `test_api.py`, `test_ui.py` (per-view render/status coverage), `test_components.py` (slippers components), `test_mcp_server.py`). Run with `./.venv/bin/python3.12 manage.py test tracking`. API tests set the token via `@override_settings(TRACKING_API_TOKEN=...)`.
- Settings are dev-only (`DEBUG=True`, hardcoded `SECRET_KEY`, console email backend). Don't rely on production config.

## REST API (`tracking/api.py`, `/tracking/api/`)
- Plain-Django JSON views (no DRF), function-based, CSRF-exempt, own `urlpatterns` `include()`d from `tracking/urls.py`. URL names are `api_`-prefixed.
- OpenAPI 3.1.0 spec at `GET /tracking/api/schema/` — loads into any OpenAPI viewer (Swagger UI, ReDoc, etc.). Schema covers all endpoints, request/response bodies, parameter descriptions, and Bearer/Cookie auth schemes.
- Endpoints: `GET /api/meta/` (enums — incl. relation types — + transition graph for discovery), `GET|POST /api/projects/`, `GET /api/projects/<key>/`, `GET|POST /api/tickets/` (filter `?project=&state=&assignee=&component=&label=`; `assignee=me|unassigned`), `GET|PATCH /api/tickets/<pk>/`, `POST /api/tickets/<pk>/transition/`, `POST /api/tickets/<id>/relations/add/` + `DELETE /api/tickets/relations/<pk>/delete/`, `GET|POST /api/comments/?ticket=`, `GET|POST /api/components/` + `GET|PATCH|DELETE /api/components/<pk>/`, `GET|POST /api/labels/?project=`, `GET|POST /api/attachments/?ticket=` (multipart upload) + `GET|DELETE /api/attachments/<pk>/`, `GET /api/sprints/<key>/` (project sprints), `POST /api/sprints/<key>/create/`, `GET|PATCH|DELETE /api/sprints/<pk>/` (DELETE refuses the backlog), `POST /api/sprints/<key>/<sprint_pk>/close/`, `GET /api/sprints/<key>/active/tickets/` (tickets of the project's single active sprint — `sprint: null` + empty list when none is active).
- State changes go **only** through `/transition/`, which reuses `ticket.can_transition_to()` (returns 409 + `allowed_transitions` on illegal moves); `PATCH` rejects a `state` key. Mirror the HTML views' state-machine discipline for any new endpoint.
- MCP integration: `make run` also starts a bundled MCP server (see Workflows above) wrapping these endpoints as agent tools. See `mcp_server.md` for client config (VS Code / Claude Desktop); ports/URL are configurable via `MCP_HOST`/`MCP_PORT`/`SMARTTRACKING_URL`.

## Authentication
- **All HTML views are `@login_required`** (`tracking/views.py`). Login/logout use Django's built-in `LoginView`/`LogoutView` (URL names `login`/`logout`); template is `templates/registration/login.html`. Settings: `LOGIN_URL="login"`, `LOGIN_REDIRECT_URL="dashboard"`, `LOGOUT_REDIRECT_URL="login"`. Logout is a POST form in `base.html`.
- **API endpoints use `@require_api_auth`** (`tracking/api.py`): accepts a logged-in session *or* a bearer token (`Authorization: Bearer <token>` / `X-API-Token`) compared against `settings.TRACKING_API_TOKEN` (from env `TRACKING_API_TOKEN`, empty disables token auth). Unauthenticated → 401 + `WWW-Authenticate: Bearer`. Decorator order is `@csrf_exempt` → `@require_api_auth` → `@require_http_methods`.
- Create users via `./.venv/bin/python3.12 manage.py createsuperuser`; run the API with a token: `TRACKING_API_TOKEN=... make run`.

