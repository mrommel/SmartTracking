# SmartTracking — TODO / Roadmap

Future improvements for this Django issue/ticket tracker, grouped into **product features**
(many inspired by JIRA), **technical improvements**, and **refactoring / code health**.
Notes reference where each item hooks into the existing architecture (see `AGENTS.md`).

Status legend: 🔴 not started · 🟡 partial · ✅ done. Priority: **P0** (do next) →
**P3** (nice to have).

---

## 🎯 Prioritized Roadmap (next up)

| # | Item | Why now | Where |
| - | ---- | ------- | ----- |
| **P0** | DB indexes on hot filter fields | Cheap, high-impact perf win; list/board/API all filter on `state`/`assignee`/`sprint`/`project` | Tech §4 |
| ~~**P0**~~ | ~~De-duplicate ticket filtering into one helper~~ | ~~`ticket_list` filter chain is inline & unshared; blocks CSV export, board, bulk, API reuse~~ | ~~Refactor §2~~ | ~~✅ done~~ |
| ~~**P1**~~ | ~~Production settings split + env config~~ | ~~Env-driven config unblocks any real deployment~~ | ~~Tech §2~~ | ~~✅ done~~ |
| ~~**P1**~~ | ~~Pagination for project-list & sprint-ticket views~~ | ~~Only remaining unpaginated lists; scales poorly~~ | ~~Tech §4~~ | ~~✅ done~~ |
| ~~**P2**~~ | ~~Caching for dashboard/report stats~~ | ~~`CACHES` is already configured — just wire `cache_page`/fragments~~ | ~~Tech §4~~ | ~~✅ done~~ |
| **P2** | Epic worklog rollups (original/remaining/spent) | Completes Time Tracking; model already exists | Product §3 |
| **P2** | API hardening (rate limit, versioning, CORS) | Only remaining API gaps | Tech §3 |
| **P3** | Profiles/Teams/Permissions, Import/Export, Custom workflows, HTMX, Full-text search, Observability | Larger efforts, lower urgency | see below |

---

## Product / Feature Improvements

### 1. Notifications & Watchers ✅ **Done**
Full notification system with in-app notifications, watcher subscriptions, @mentions, and complete
REST API. Integration via `TicketActivity` signal (`post_save`) and automatic email-ready delivery.
- [x] `Watcher` model (`ticket` FK + FK to `User`) with UI to manage watchers on ticket detail.
- [x] `Notification` model (`ticket`, `recipient`, `actor`, `verb`, `body`, `read`) stored in DB,
      displayed in in-app notification feed.
- [x] Automatic in-app notifications on: ticket creation, state change, sprint change, title change,
      assignment change, comment creation, @mentions.
- [x] @mention parsing in comments via `mistune` markdown renderer with `@username` regex.
- [x] Automatic assignment auto-subscribes the assignee and optionally notifies them.
- [x] Reusable `_deliver_ticket_event()` helper notifies all watchers + reporter; deduplicates
      existing verbs; skips no-op self-notifications via `_create_for()`.
- [x] Notification views: feed list (`pagination_page_view`), mark-read (single + "mark all"),
      delete individual.
- [x] REST API endpoints: collection/list/mark-read/mark-all-read/delete at `/tracking/api/notifications/`;
      watchers (list/create/remove) at `/tracking/api/tickets/<pk>/watchers/`;
      workspace watcher list/add/remove at `/tracking/api/watchers/`.
- [x] Full test suite (8 NotificationSignalTests + 11 NotificationApiTests + 5 WatcherViewTests +
      13 WatcherApiTests — 37 tests total, all passing).

### 2. Search & Filtering upgrades ✅ **Done**
`ticket_list()` has a free-text query bar with ticket-key search, multi-value filter pills, sort
controls, and saved named filters per user.
- [x] **Multi-value filters** using `request.GET.getlist()` for `state`, `label`, `component`, and
  `assignee` (logical AND across values of the same group, logical OR across groups).
- [x] **Ticket-key search** — numeric queries also match on primary-key lookup (`pk`) so a typed
  `SMT-1` (stored as `1`) returns the expected ticket; falls back to title/description `icontains`.
- [x] **Sort controls** — `<select>` (`SORT_MAP`) with `title`, `type`, `priority`, `state`,
  `due_date`, `created`, `updated` keys plus an `asc`/`desc` toggle and custom priority ordering.
- [x] **Query bar + active-pills** — a top-level search input paired with badge pills for each
  active filter, kept in sync client-side.
- [x] **Saved filters** — `SavedFilter` model (`name`, `filters_json`, `is_active`, FK to `Project`
  and `User`) with save / apply / delete cycles; user-scoped "Saved filters" dropdown.
- [x] **Pagination preserving filters** — active query params serialized into pagination URLs.
- [x] **Shared `build_ticket_queryset()` helper** in `tracking/queryset_helpers.py` — the entire
  inline filter chain (state, label, component, assignee/me/unassigned, project, free-text `query`,
  sort + order) is extracted and reused by the HTML view, API list, board, and future bulk/CSV
  endpoints. Unit tests in `BuildTicketQuerySetTests`.
- [ ] **Full-text search** (SQLite FTS5 / Postgres `SearchVector`) covering comments too. 🔴 **P3**

### 3. Time Tracking / Worklog 🟡 **Partial**
- [x] `WorkLog` model (time spent, remaining estimate, date, author) + a "Log work" action.
- [ ] **Original vs remaining vs spent rollups on epics** (aggregate child `WorkLog`s up
      `parent_epic`). 🟡 **P2**

### 4. User Profiles, Teams & Permissions 🔴 **P3**
- [x] User profile page (avatar, tickets assigned, activity feed).
- [ ] **Project-level roles/membership** and permission checks in the `views/` package.
- [ ] Object-level permissions (e.g. `django-guardian`) or per-project membership.

### 5. Import / Export 🔴 **P3**
- [ ] **CSV export** of filtered ticket lists (reuse the shared queryset from Refactor §2).
- [ ] **CSV / JIRA import** to migrate existing issues.
- [ ] Per-ticket export/print view.

### 6. Custom Fields & Configurable Workflows 🔴 **P3**
- [ ] Admin-configurable **custom fields** per project/type.
- [ ] **Configurable state machine** per project instead of hardcoded `Ticket.TRANSITIONS`.
- [ ] Transition **rules/validators** (e.g. require assignee before `IN_PROGRESS`,
      resolution reason on `RESOLVED`).

### ✅ Already implemented (product)
- **Sprint Velocity Analytics** — `SprintMetrics` model, `Sprint.calculate_metrics()`, velocity page
  with Chart.js, velocity tab in `project_detail`, REST `sprint_velocity_collection` endpoint.
- **Notifications & Watchers** — see §1 (37 tests).
- **Reporting & Analytics** — burndown/burnup, velocity, cumulative flow, dashboard widgets
  (priority/workload/overdue/aging), created-vs-resolved trend.
- **Activity Log** — `TicketActivity` model + chronological timeline merged with comments.
- **Bulk Operations** — `BulkActionForm` + `ticket_bulk_action` (state, reassign, labels,
  components, sprint, delete) with a JS bulk bar and tests.
- **Agile Board** — drag-and-drop Kanban (SortableJS + REST transitions), swimlanes, WIP limits,
  board tab in `project_detail`.
- **Epic & Backlog** — epic progress bars, sub-tasks as a distinct type, drag-to-rank backlog.
- **Attachments & Comments** — inline image gallery, comment edit/delete with history,
  drag-and-drop / paste-to-attach upload.
- **Releases / Versions** — `Version` model, `fix_version`/`affects_versions`, release notes
  generation, version roadmap.
- **Pagination** — `ticket_list` (25/page, filters preserved) and `ticket_detail` comments
  (20/page), `project_list` (25/page), backlog/sprint-ticket views in `project_detail` (10 sprints/page, all tabs).

---

## Technical Improvements

### 1. Testing & Quality ✅
- [x] Coverage measurement (`coverage.py`) with an 80% threshold.
- [x] Type hints across models/views/api + `mypy`/`pyright` config.
- [x] Linting/formatting (`ruff` + `black`, tabs convention) and pre-commit hooks.
- [x] GitHub Actions CI (`.github/workflows/ci.yml`): migrations check, tests + coverage,
      ruff/black lint, translation compilation.
- [x] **CI translation guard** (`scripts/check_translations.py`) — regenerates catalogs, checks every
      `msgid` has a non-empty `msgstr`, compiles `.mo` files, fails on any untranslated/stale string.

### 2. Production settings & Deployment ✅ **Done**
`setup/settings.py` is a single dev-only file (`DEBUG=True`, hardcoded `SECRET_KEY`, console email,
`ALLOWED_HOSTS=[]`).
- [x] **Env-driven settings** (`django-environ`): `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`,
      DB URL (Postgres option), real email backend.
- [x] **Production settings split** (`settings/base.py` + `dev.py` + `prod.py`, or env-gated).
- [x] Static via WhiteNoise/CDN.
- [ ] **Dockerfile + docker-compose** for reproducible dev/prod.

### 3. API hardening (`tracking/api/`) 🟡 **P2**
- [x] OpenAPI 3.1.0 spec at `/tracking/api/schema/` (hand-written, extracted to `api/schema.py`).
- [x] Pagination + consistent envelope (`page`/`page_size` → `{count, pagination, results}`).
- [x] Serializer helpers (`_parse_json`, `_valid_required`, `_valid_optional` in `api/_common.py`).
- [ ] **Rate limiting** and **API versioning** (`/api/v1/`).
- [ ] **CORS** config if external clients are expected.

### 4. Performance 🟡 **P0**
- [x] `select_related`/`prefetch_related` used across list/detail views.
- [x] `CACHES` backend configured (LocMemCache) in `settings.py` — not yet used by any view.
- [x] **DB indexes** (`db_index=True` / `Meta.indexes`) on frequently filtered fields
      (`state`, `assignee`, `sprint`, `due_date`, `project`) — only `TicketActivity.action`
      is indexed today. 🔴 **P0**
- [x] Wire the configured cache to **dashboard/report stats** (`cache_page` or fragment caching). 🟡 **P2** — ✅ `@cache_page` added to `dashboard`, `project_detail`, `sprint_velocity`, `reports`, and `releases` views; `{% cache 300 %}` fragments in `dashboard.html` (project table), `project_detail.html` (overview stats, charts, sidebar, reports tab, releases tab), `reports.html` (stat cards + detail panels), and `releases.html` (versions table). Timeout configurable via `DASHBOARD_CACHE_TIMEOUT` (300s when DEBUG=False, 0 when DEBUG=True to disable caching in dev/test).
- [x] Add pagination to the **project list** and **sprint-ticket** views. 🔴 **P1**

### 5. Security 🟡
- [x] Constant-time API token comparison (`hmac.compare_digest`).
- [x] Move `SECRET_KEY` and secrets to env; never commit (see Tech §2).
- [ ] Security middleware for prod (HSTS, secure cookies, `SECURE_SSL_REDIRECT`).
- [ ] **File upload hardening** beyond extension/MIME; correct `Content-Disposition` on download.

### 6. Frontend / UX 🔴 **P3**
- [ ] Adopt **HTMX** for progressive enhancement (inline transitions, comment posting,
      board drag-drop) consistent with the "no JS framework" goal.
- [ ] **Accessibility** pass (ARIA on badges, form labels, keyboard nav).
- [x] **Dark mode** toggle (Bootstrap 5.3 `data-bs-theme`, `localStorage` persistence,
      `prefers-color-scheme` fallback).

### 7. Observability 🟡
- [x] Health-check endpoint (`GET /health/` → `{"status": "ok"}` / 503 on DB failure).
- [ ] Structured **logging** config (`LOGGING` dict) and request logging. 🔴 **P3**
- [ ] Error monitoring (Sentry) wired via env. 🔴 **P3**

### 8. Data integrity & migrations ✅ **Done**
- [x] Model-level `constraints` complementing `save()`-based enforcement: `UniqueConstraint`
      for `TicketRelation`, a partial constraint for "one active sprint per project", and
      `unique_together` → `UniqueConstraint` migrations (see `models.py`).
- [x] Parameterize the Makefile's hardcoded `sqlmigrate tracking 0001`.

### 9. Internationalization ✅
- [x] `gettext_lazy` used consistently; `LANGUAGES` + `LOCALE_PATHS` configured.
- [x] CI translation guard (`scripts/check_translations.py`) that regenerates catalogs, verifies every
      `msgid` has a `msgstr`, and compiles `.mo` files.

---

## Refactoring / Code Health

### 1. Split the oversized modules ✅ **Done**
- [x] **`tracking/api.py`** — split into an `api/` package grouped by resource (tickets, sprints,
      comments, attachments, relations, watchers, notifications, worklogs, …); the OpenAPI schema
      lives in `api/schema.py` and shared helpers in `api/_common.py`.
- [x] **`tracking/views.py`** — split into a `views/` package by domain (`ticket_views.py`,
      `project_views.py`, `sprint_views.py`, `report_views.py`, `bulk_views.py`,
      `notification_views.py`, `watcher_views.py`, `saved_filter_views.py`, `version_views.py`, …).

### 2. De-duplicate ticket filtering ✅ **Done**
- [x] The `ticket_list()` filter chain (state/label/component/assignee/query/sort) extracted into a
      single `build_ticket_queryset(request, project_key=None, labels_by_id=False, components_by_id=False)`
      helper in `tracking/queryset_helpers.py`. Reused by the HTML view and API list endpoint.
      Full unit test suite in `BuildTicketQuerySetTests`.
- [x] Priority maps (`PRIORITY_ORDER`) consolidated — the inline `priority_map` in `ticket_views.py`
      replaced with a reference to `Ticket.Priority` enum values.
- [ ] Fold remaining function-local `from django.db.models import Case, When, ...` imports to module
      top (minor).

### 3. Misc cleanups
- [x] Fold repeated per-endpoint JSON parsing into `api/_common.py::parse_json` and eliminate 10 scattered `json.loads`/try-except blocks, plus remove 4 `import json` statements and 2 dual-imports across the `api/` package.
- [ ] Audit remaining N+1 risks on detail views (relations, labels, components, comments).
- [x] Keep new strings wrapped in `gettext_lazy` (enforced via the CI guard in Tech §1/§9).

