# SmartTracking

A Django 6.1 issue and sprint tracker with a built-in REST API and MCP (Model Context Protocol) server for AI agent integration.

[![Django 6.1](https://img.shields.io/badge/Django-6.1-blue)](https://www.djangoproject.com/)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

## Features

- **Project & Sprint management** — organize work into projects with time-boxed sprints, components, and labels
- **Ticket tracking** — create and manage tasks, bugs, stories, epics, and sub-tasks with a full state machine (Open → In Progress → Resolved → Closed)
- **Sprint metrics** — velocity charts, completion rates, waste ratios, and effort estimation
- **Ticket relations** — link tickets with blocked-by, related-to, and tested-with relationships (auto-symmetrized)
- **Version tracking** — track releases, fix versions, and auto-generate release notes
- **Comments & attachments** — threaded discussions and file attachments (PNG, JPG, PDF, JSON, TXT, LOG) up to 10 MB
- **Time tracking** — work logs with per-user time entry
- **Notifications** — in-app notifications for assignments, mentions, and state changes
- **Saved filters** — persist custom ticket list views per user
- **Activity logs** — audit trail for all ticket changes
- **i18n** — full translation support (English + German)
- **REST API** — JSON API with pagination, filtering, and an OpenAPI 3.1.0 schema
- **MCP integration** — drive tickets from AI agents via the Model Context Protocol

## Quick Start

```bash
# 1. Create and activate the virtual environment
make venv
source .venv/bin/activate

# 2. Copy the example environment file
cp .env.example .env
# Edit .env and set TRACKING_API_TOKEN

# 3. Create a superuser
./manage.py createsuperuser

# 4. Start the dev server + MCP server
make run
```

The application runs at `http://127.0.0.1:8092` and the MCP server at `http://127.0.0.1:8091/mcp`.

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make venv` | Create the virtual environment and install dependencies |
| `make run` | Start the dev server (port 8092) + MCP server (port 8091) |
| `make migrate` | Apply database migrations |
| `make makemigrations` | Create new migrations |
| `make test` | Run the full test suite with coverage |
| `make coverage-report` | Generate an HTML coverage report at `htmlcov/index.html` |
| `make clean` | Remove the virtual environment and compiled files |
| `make preparetranslations` | Extract translatable strings |
| `make compiletranslations` | Compile translation files |

## Architecture

```
SmartTracking/
├── setup/              # Django project config (settings, URLs, ASGI/WSGI)
├── tracking/           # Single app — all domain logic
│   ├── models.py       # Project, Ticket, Sprint, Comment, Attachment, WorkLog, etc.
│   ├── views/          # Function-based views (login_required)
│   ├── api.py          # JSON REST API (CSRF-exempt, bearer token auth)
│   ├── urls.py         # URL routing
│   ├── admin.py        # Django admin configuration
│   ├── forms.py        # Form definitions (Crispy Bootstrap5)
│   ├── signals.py      # Auto-created entities (backlog sprint, initial labels)
│   ├── templates/      # Bootstrap 5 templates + Slippers components
│   ├── templatetags/   # Custom template tags (type_badge, priority_badge, markdown)
│   ├── static/         # CSS, JS, images
│   └── tests/          # Unit + integration tests
├── mcp_server.py       # MCP server (model context protocol for AI agents)
├── mcp_server.md       # MCP client configuration guide
├── requirements.txt    # Python dependencies
├── pyproject.toml      # Black + Ruff formatting config
├── Makefile            # Development commands
└── .env.example        # Environment variable template
```

## Data Model

| Model | Description |
|-------|-------------|
| **Project** | Groups tickets, sprints, components, and labels |
| **Ticket** | Unit of work — task, bug, story, epic, or sub-task with state machine |
| **Sprint** | Time-boxed iteration with metrics (velocity, waste ratio, completion) |
| **Component** | Logical grouping of tickets within a project |
| **Label** | Color-coded tags for tickets |
| **Version** | Software releases with release note generation |
| **Comment** | Markdown-enabled discussions on tickets |
| **Attachment** | File uploads with MIME validation |
| **WorkLog** | Per-user time tracking entries |
| **TicketRelation** | Directed, auto-symmetric links between tickets |
| **ActivityLog** | Audit trail for ticket changes |
| **Notification** | In-app notifications for assignments and mentions |
| **Watcher** | Users subscribed to ticket changes |
| **SavedFilter** | Persisted custom ticket list views |

## Authentication

| Layer | Method |
|-------|--------|
| **HTML views** | Django session auth (`@login_required`) |
| **REST API** | Session auth or bearer token (`TRACKING_API_TOKEN`) |
| **MCP server** | Bearer token to call the REST API |

## REST API

Plain-Django JSON views at `/tracking/api/` with OpenAPI 3.1.0 schema at `GET /tracking/api/schema/`.

**Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/meta/` | Enums + state-transition graph |
| `GET,POST` | `/api/projects/` | List / create projects |
| `GET` | `/api/projects/<key>/` | Project detail |
| `GET,POST` | `/api/tickets/` | List (filterable) / create tickets |
| `GET,PATCH` | `/api/tickets/<pk>/` | Ticket detail / update |
| `POST` | `/api/tickets/<pk>/transition/` | State transition |
| `POST` | `/api/tickets/<id>/relations/add/` | Add ticket relation |
| `DELETE` | `/api/tickets/relations/<pk>/delete/` | Delete ticket relation |
| `GET,POST` | `/api/comments/?ticket=` | List / create comments |
| `GET,POST` | `/api/attachments/?ticket=` | List / upload attachments |
| `GET,DELETE` | `/api/attachments/<pk>/` | Attachment detail / delete |
| `GET,POST` | `/api/sprints/<key>/` | Project sprints |
| `GET,PATCH,DELETE` | `/api/sprints/<pk>/` | Sprint CRUD |
| `POST` | `/api/sprints/<key>/<pk>/close/` | Close a sprint |
| `GET` | `/api/sprints/<key>/active/tickets/` | Active sprint tickets |
| `GET,POST` | `/api/components/` | List / create components |
| `GET,PATCH,DELETE` | `/api/components/<pk>/` | Component CRUD |
| `GET,POST` | `/api/labels/?project=` | List / create labels |

All list endpoints return paginated envelopes: `{ "count": N, "pagination": {...}, "results": [...] }`.

## AI Agent Integration (MCP)

SmartTracking ships an MCP server that exposes ticket operations as tools for LLM agents.

```bash
# Start with MCP server (port 8091) + Django (port 8092)
TRACKING_API_TOKEN=my-secret-token make run
```

### Available MCP tools

| Tool | Description |
|------|-------------|
| `get_meta` | Discover enums and state transitions |
| `list_projects` / `get_project` / `create_project` | Project CRUD |
| `list_tickets` / `get_ticket` / `create_ticket` | Ticket listing and creation |
| `update_ticket` | Update ticket fields (not state) |
| `transition_ticket` | Change ticket state via the state machine |
| `list_sprints` | List sprints for a project |
| `get_active_sprint_tickets` | Tickets in the active sprint |

See `mcp_server.md` for VS Code, Claude Desktop, Cursor, and Windsurf client configuration.

## Testing

```bash
# Run all tests with coverage
make test

# Generate HTML coverage report
make coverage-report
# Open htmlcov/index.html in a browser
```

## Configuration

Copy `.env.example` to `.env` and adjust:

| Variable | Default | Description |
|----------|---------|-------------|
| `TRACKING_API_TOKEN` | *(empty)* | Bearer token for API / MCP auth |
| `SMARTTRACKING_URL` | `http://127.0.0.1:8092` | Django app base URL |
| `MCP_HOST` | `127.0.0.1` | MCP server bind address |
| `MCP_PORT` | `8091` | MCP server port |

## License

MIT
