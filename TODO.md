# SmartTracking — TODO / Roadmap

A list of possible future improvements, grouped into **product features** (many inspired by
JIRA's feature set) and **technical improvements**. Notes reference where each item hooks into
the existing architecture.

---

## Product / Feature Improvements

### 1. Reporting & Analytics (finish the placeholders)
`reports()` and `releases()` in `views.py` are currently "coming soon" stubs
(`reports.html`, `releases.html`).
- [x] **Burndown / burnup charts** for the active sprint (leverage `estimation` + state changes).
- [x] **Velocity chart** across closed sprints (story points completed per sprint).
- [x] **Cumulative flow diagram** by state.
- [x] **Dashboard widgets**: tickets by priority, by assignee workload, overdue tickets
      (uses existing `due_date`), aging report for stale `OPEN`/`IN_PROGRESS`.
- [x] **Created-vs-resolved trend** over time.

### 2. Activity Log / Change History
No audit trail today. JIRA's "History" tab is core.
- [x] Add a `TicketActivity`/`AuditLog` model recording state transitions, field edits,
      assignments, relation/label/component changes.
- [x] Render a chronological "Activity" timeline on `ticket_detail.html` merged with comments.
- [x] Consider `django-simple-history` or a lightweight signal-based logger.

### 3. Notifications & Watchers
No notification system exists (email backend is console-only).
- [ ] **Watchers/subscriptions** (`Ticket.watchers` M2M) so users follow tickets.
- [ ] **@mentions** in comments (markdown already rendered via `mistune`).
- [ ] **Email/in-app notifications** on assignment, state change, new comment, mention.
- [ ] Assignment auto-subscribes the assignee.

### 4. Search & Filtering upgrades
`ticket_list()` only does `icontains` on title/description plus a few exact filters.
- [ ] **Saved filters / named views** (a `SavedFilter` model per user).
- [ ] **Full-text search** (Postgres `SearchVector` or SQLite FTS5) covering comments too.
- [ ] **Combined multi-value filters** (multiple states/labels/assignees at once), sort controls,
      and **quick text query on ticket key**.
- [ ] A **JQL-style query bar** as an advanced option.

### 5. Bulk Operations
No batch editing today.
- [ ] Multi-select on `ticket_list` to bulk transition, reassign, add labels/components,
      move to sprint, or delete.

### 6. Agile Board (Kanban / Scrum board)
Currently only list + sprint views (`active_sprint.html`).
- [ ] **Drag-and-drop board** with columns per `State` (HTMX + Sortable, minimal JS).
- [ ] Swimlanes by assignee/epic/priority.
- [ ] WIP limits per column.

### 7. Time Tracking / Worklog
`estimation` exists but no logging of actual work.
- [ ] `WorkLog` model (time spent, remaining estimate, date, author) with a "Log work" action.
- [ ] Original vs remaining vs spent rollups on epics.

### 8. Epic & Backlog enhancements
Epics exist (`parent_epic`), but:
- [ ] **Epic progress bar** (child completion %) on detail and board.
- [ ] **Sub-tasks** as a distinct type or checklist items.
- [ ] **Backlog ranking** (drag-to-prioritize ordering field) beyond current sprint assignment.

### 9. Pagination
~No pagination somewhere — `ticket_list`, `project_detail`, comments render all rows.~ **Done** — added Django `Paginator` to:
- `ticket_list` view (25 tickets per page, preserved all filter query params)
- `ticket_detail` comments (20 comments per page)
- [ ] **Project list** page pagination (for many-projects scenario).
- [ ] **Sprint ticket views** pagination.

### 10. User Profiles, Teams & Permissions
No profile/role model.
- [ ] User profile page (avatar, tickets assigned, activity).
- [ ] **Project-level roles/permissions** (currently any logged-in user can do anything).
- [ ] Object-level permissions (e.g. `django-guardian`) or per-project membership.

### 11. Import / Export
- [ ] **CSV export** of filtered ticket lists.
- [ ] **CSV/JIRA import** to migrate existing issues.
- [ ] Per-ticket export/print view.

### 12. Attachments & Comments polish
- [ ] **Inline image thumbnails / gallery** (already detect `is_image`).
- [ ] **Comment editing/deletion** with edit history.
- [ ] **Drag-and-drop upload** and paste-to-attach.

### 13. Custom Fields & Workflows
- [ ] Admin-configurable **custom fields** per project/type.
- [ ] **Configurable state machine** per project instead of the hardcoded `Ticket.TRANSITIONS`.
- [ ] Transition **rules/validators** (e.g. require assignee before `IN_PROGRESS`,
      resolution reason on `RESOLVED`).

### 14. Releases / Versions
~`releases()` is a stub.~ Implemented with `Version` model and full CRUD.
- [x] A `Version` model with `fix_version` and `affects_versions` on tickets,
      release notes generation, and a version roadmap.
- [ ] **Release notes generation** from resolved tickets in a version.
- [ ] **Version roadmap** (visual timeline of planned vs released versions).

---

## Technical Improvements

### 1. Testing & Quality
- [x] Add **coverage measurement** (`coverage.py`) and enforce a threshold.
- [x] **Type hints** across `models.py`/`views.py`/`api.py` + `mypy`/`pyright` config.
- [x] **Linting/formatting**: `ruff` + `black` (note: tabs convention — configured in pyproject.toml)
      and **pre-commit hooks**.

### 2. CI/CD
- [x] Added **GitHub Actions** pipeline (`.github/workflows/ci.yml`) running:
  migrations check, tests (with 80% coverage threshold), ruff+black linting, and
  translation compilation.

### 3. Containerization & Deployment
- [ ] **Dockerfile + docker-compose** for reproducible dev/prod.
- [ ] **Production settings split** — `settings.py` is dev-only (`DEBUG=True`, hardcoded
      `SECRET_KEY`, console email). Introduce env-driven settings (`django-environ`),
      Postgres option, `ALLOWED_HOSTS`, static via WhiteNoise/CDN, real email backend.

### 4. API hardening (`tracking/api.py`)
- [x] **OpenAPI/Swagger docs** (hand-written OpenAPI 3.1.0 spec at `/tracking/api/schema/` — no external dependency).
- [x] **Pagination + consistent envelope** for list endpoints (query params `page`/`page_size`, returns `{ "count", "pagination": {"next", "previous"}, "results" }`).
- [ ] **Rate limiting** and **API versioning** (`/api/v1/`).
- [ ] **CORS** config if external clients are expected.
- [ ] Consolidate hand-rolled JSON handling (repeated validation) into small serializer helpers.

### 5. Performance
- [ ] Audit `select_related`/`prefetch_related` on list/detail views to prevent N+1
      (relations, labels, components, comments).
- [ ] Add **DB indexes** on frequently filtered fields (`state`, `assignee`, `sprint`,
      `due_date`, `project`).
- [ ] Introduce **caching** (per-view or fragment) for dashboard stats.

### 6. Security
- [ ] Move `SECRET_KEY` and all secrets to env; never commit.
- [ ] Add security middleware settings for prod (HSTS, secure cookies, `SECURE_SSL_REDIRECT`).
- [ ] **File upload hardening**: scanning beyond extension/MIME, correct `Content-Disposition`.
- [ ] Constant-time token comparison for `TRACKING_API_TOKEN` (`secrets.compare_digest`).

### 7. Frontend / UX
- [ ] Adopt **HTMX** for progressive enhancement (inline transitions, comment posting,
      board drag-drop) consistent with the "no JS framework" goal.
- [ ] **Accessibility** pass (ARIA on badges, form labels, keyboard nav).
- [ ] Dark mode toggle (Bootstrap 5.3 color modes).

### 8. Observability
- [ ] Structured **logging** config and request logging.
- [ ] Error monitoring (Sentry) wired via env.
- [ ] Health-check endpoint.

### 9. Data integrity & migrations
- [ ] Add model-level `constraints` (e.g. `CheckConstraint` for one active sprint,
      `UniqueConstraint` for relations) to complement the `save()`-based enforcement.
- [ ] Fix the Makefile note that **hardcodes `sqlmigrate tracking 0001`** — parameterize it.

### 10. Internationalization
- [ ] Ensure all new strings use `gettext_lazy`; add a CI check that translations are compiled
      and no `msgid` is untranslated.

---

## Suggested Prioritization (quick wins → high value)
1. ~~**Pagination** + list-view `select_related`/indexes (fast, broad impact).~~ **Done** — ticket_list + comments paginated.
2. **Activity log** (unblocks history + notifications).
3. ~~**Reports/burndown** (finishes visible stubs).~~ **Done** — full reports and releases are implemented.
4. **CI + linting + coverage** (quality foundation).
5. **Notifications/watchers**, then **agile board** and **bulk actions**.

