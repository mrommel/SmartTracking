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
| **P1** | Production settings split | Env-driven config unblocks any real deployment | Tech §2 |
| **P2** | Time Tracking / WorkLog | Natural extension of existing `estimation` | Product §3 |
| **P2** | API hardening (rate limit, versioning, CORS) | Only remaining API gaps | Tech §3 |
| **P3** | Profiles/Teams/Permissions, Import/Export, Custom workflows, HTMX/dark mode | Larger efforts, lower urgency | see below |

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
`ticket_list()` features a centralized `_build_tickets_queryset()` helper, a free-text query bar with ticket-key search,
multi-value filter pills, sort controls, and saved named filters per user.
- [x] **Centralised queryset builder** (`_build_tickets_queryset`) with single and multi-value filter support
  using `request.GET.getlist()` for `state`, `label`, `component`, and `assignee` (logical AND across values of
  the same group, logical OR across groups).
- [x] **Ticket-key search** — resolves numeric query parameters via model primary-key lookup (`pk`)
  so a typed `SMT-1` (stored as `1`) returns the expected ticket. Falls back to title/description `icontains`
  otherwise.
- [x] **Sort controls** — `<select>` with `title`, `type`, `priority`, `state`, `due_date`, `created_at`,
  `updated_at` keys plus an `asc`/`desc` toggle; rendered upfront in the template and wired to the server-side
  `sort_map`/`order` logic.
- [x] **Query bar + active-pills** — a top-level search input paired with badge pills for each active filter
  (state, label, component, assignee) that the JS `_add_filter_pills()` renders and keeps in sync
  (toggle-removal resets the pill via `removeParam`).
- [x] **Saved filters** — a `SavedFilter` model (`name`, `filters_json` dict, `is_active`, FK to `Project`
  and `User`). View exports current GET params to a session dict on every ticket-list render; the
  "Save as filter" modal captures the name and stores the dict; saving uses `get_or_create` (upsert) so
  repeated saves overwrite the stored dict. A "Saved filters" dropdown renders user-scoped active filters;
  POST to apply one, auto-redirects the HTML list to the computed query-string URL.
- [x] **Pagination preserving filters** — `page_obj.next_page_url` / `previous_page_url` strip the `page`
  key while keeping all active query params auto-serialized into the `pagination_params` string.
- [x] **JQL-style query bar** — free-text filters that combine all active conditions.
- [ ] **Full-text search** (SQLite FTS5 / Postgres `SearchVector`) covering comments too.
- [ ] A **JQL-style query bar** as an advanced option.

### 3. Time Tracking / Worklog ✅ **Done**
- [x] `WorkLog` model (time spent, remaining estimate, date, author) + a "Log work" action.
- [ ] Original vs remaining vs spent rollups on epics.

### 4. User Profiles, Teams & Permissions 🔴 **P3**
- [x] User profile page (avatar, tickets assigned, activity feed).
- [ ] **Project-level roles/membership** and permission checks in `views.py`.
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
- **Search & Filtering upgrades** — centralized `_build_tickets_queryset` supporting multi-value query parameters
  (`state`, `label`, `component`, `assignee`) with AND semantics within a group. Ticket-key search via id lookup,
  sort controls (`title`, `type`, `priority`, `state`, `due_date`, `created_at`, `updated_at`), free-text query bar,
  active filter pills rendered in the template, and a `SavedFilter` model per user (save / apply / delete cycles).
  Pagination preserving all active query params in `page_obj.next_page_url` / `previous_page_url`.
- **Sprint Velocity Analytics** — `SprintMetrics` model (`total_points`, `completed_points`,
  `total_tickets`, `completed_tickets`, `duration_days`), `Sprint.calculate_metrics()` that
  auto-computes and stores sprint performance, standalone velocity page with KPI cards and
  Chart.js (Completion Trend + Points Burn-Down), velocity tab in `project_detail` with inline
  Chart.js rendering, velocity insights sidebar on sprint create/edit, REST API
  `sprint_velocity_collection` endpoint at `/tracking/api/`, migration `0019_sprintmetrics.py`.
- **Notifications & Watchers** — `Notification` model (`ticket`, `recipient`, `actor`, `verb`, `body`,
  `read`), `Watcher` model (`ticket` FK + `user` FK), signal-driven delivery on create/state-change/sprint-change/title-change/assign/comment/@mention, in-app notification feed with mark-read/delete, REST API (collection/list/mark-read/mark-all-delete / watchers/workspace watchers), plus 37 tests.
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
  (20/page). Still open: project-list and sprint-ticket views (tracked in Tech §4).

---

## Technical Improvements

### 1. Testing & Quality ✅ / 🟡
- [x] Coverage measurement (`coverage.py`) with an 80% threshold.
- [x] Type hints across `models.py`/`views.py`/`api.py` + `mypy`/`pyright` config.
- [x] Linting/formatting (`ruff` + `black`, tabs convention) and pre-commit hooks.
- [x] GitHub Actions CI (`.github/workflows/ci.yml`): migrations check, tests + coverage,
      ruff/black lint, translation compilation.
- [ ] **CI translation guard** — fail if any `msgid` is untranslated / catalogs are stale (i18n).

### 2. Production settings & Deployment 🔴 **P1**
`settings.py` is dev-only (`DEBUG=True`, hardcoded `SECRET_KEY`, console email, `ALLOWED_HOSTS=[]`).
- [ ] **Env-driven settings** (`django-environ`): `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`,
      DB URL (Postgres option), real email backend.
- [ ] **Production settings split** (`settings/base.py` + `dev.py` + `prod.py`, or env-gated).
- [ ] Static via WhiteNoise/CDN.
- [ ] **Dockerfile + docker-compose** for reproducible dev/prod.

### 3. API hardening (`tracking/api.py`) 🟡 **P2**
- [x] OpenAPI 3.1.0 spec at `/tracking/api/schema/` (hand-written, no external dep).
- [x] Pagination + consistent envelope (`page`/`page_size` → `{count, pagination, results}`).
- [x] Serializer helpers (`_parse_json`, `_valid_required`, `_valid_optional`).
- [ ] **Rate limiting** and **API versioning** (`/api/v1/`).
- [ ] **CORS** config if external clients are expected.

### 4. Performance 🟡 **P0**
- [x] `select_related`/`prefetch_related` used across list/detail views.
- [ ] Add **DB indexes** (`db_index=True` / `Meta.indexes`) on frequently filtered fields
      (`state`, `assignee`, `sprint`, `due_date`, `project`) — only `TicketActivity.action`
      is indexed today.
- [ ] Introduce **caching** (per-view or fragment) for dashboard/report stats.
- [ ] Add pagination to the **project list** and **sprint-ticket** views.

### 5. Security 🟡
- [x] Constant-time API token comparison (`hmac.compare_digest`).
- [ ] Move `SECRET_KEY` and secrets to env; never commit (see Tech §2).
- [ ] Security middleware for prod (HSTS, secure cookies, `SECURE_SSL_REDIRECT`).
- [ ] **File upload hardening** beyond extension/MIME; correct `Content-Disposition` on download.

### 6. Frontend / UX 🔴 **P3**
- [ ] Adopt **HTMX** for progressive enhancement (inline transitions, comment posting,
      board drag-drop) consistent with the "no JS framework" goal.
- [ ] **Accessibility** pass (ARIA on badges, form labels, keyboard nav).
- [ ] **Dark mode** toggle (Bootstrap 5.3 color modes).

### 7. Observability 🟡
- [x] Health-check endpoint (`GET /health/` → `{"status": "ok"}` / 503 on DB failure).
- [ ] Structured **logging** config (`LOGGING` dict) and request logging.
- [ ] Error monitoring (Sentry) wired via env.

### 8. Data integrity & migrations 🟡 **P0**
- [ ] Add model-level `constraints` to complement `save()`-based enforcement:
      `UniqueConstraint` for `TicketRelation`, a partial `UniqueConstraint`/`CheckConstraint`
      for "one active sprint per project", and migrate `unique_together` → `UniqueConstraint`.
- [ ] Parameterize the Makefile's hardcoded `sqlmigrate tracking 0001`.

### 9. Internationalization 🟡
- [x] `gettext_lazy` used consistently; `LANGUAGES` + `LOCALE_PATHS` configured.
- [ ] CI check that catalogs are compiled and no `msgid` is untranslated (see Tech §1).

---

## Refactoring / Code Health

### 1. Split the oversized modules 🔴 **P1**
- [ ] **`tracking/api.py` (~2000 lines)** — extract the hand-written OpenAPI schema into
      `tracking/api_schema.py` and group endpoint views by resource (tickets, sprints,
      comments, attachments…) into an `api/` package.
- [ ] **`tracking/views.py` (~1600 lines)** — split into a `views/` package by domain
      (`ticket_views.py`, `project_views.py`, `sprint_views.py`, `report_views.py`, …).

### 2. De-duplicate ticket filtering 🔴 **P1**
- [ ] `ticket_list()` and `_build_tickets_queryset()` reimplement the same filter chain.
      Extract a single `build_ticket_queryset(params)` helper reused by the HTML view,
      bulk actions, board, and (future) CSV export / API list.

### 3. Misc cleanups
- [ ] Fold repeated per-endpoint validation in `api.py` further into the serializer helpers.
- [ ] Audit remaining N+1 risks on detail views (relations, labels, components, comments).
- [ ] Keep new strings wrapped in `gettext_lazy` (enforced via the CI guard in Tech §1/§9).

