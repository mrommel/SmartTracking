# SmartTracking MCP Server

SmartTracking ships an MCP server that is **started automatically by `make run`**,
alongside the Django dev server. Once `make run` is up, an LLM agent in another
project can connect to it over the network and drive tickets/projects as tools.

- Django app (HTML + REST API): `http://127.0.0.1:8092`
- **MCP server (streamable HTTP): `http://127.0.0.1:8091/mcp`**

The implementation lives in `mcp_server.py`. Each MCP tool is a thin wrapper
around a REST endpoint in `tracking/api.py`; all domain rules (valid enums, the
state-transition graph, auth) stay enforced by the Django API.

An **OpenAPI 3.1.0 spec** is available at `GET /tracking/api/schema/` — loads
into Swagger UI, ReDoc, or any OpenAPI viewer for a complete machine-readable
description of every endpoint, parameter, and response type.

---

## 1. Start it

```bash
TRACKING_API_TOKEN=my-secret-token make run
```

`make run` sources `.env`, launches `mcp_server.py` in the background, then runs
`manage.py runserver 8092` in the foreground. Stopping `make run` (Ctrl-C) also
stops the MCP server. The MCP server authenticates to the REST API with
`TRACKING_API_TOKEN`, so set it (see `.env.example`) or the API returns 401.

Configuration (all optional, read from the environment / `.env`):

| Variable             | Default                 | Meaning                                   |
|----------------------|-------------------------|-------------------------------------------|
| `SMARTTRACKING_URL`  | `http://127.0.0.1:8092` | Base URL of the Django app the tools call |
| `TRACKING_API_TOKEN` | *(empty)*               | Bearer token used to call the REST API    |
| `MCP_HOST`           | `127.0.0.1`             | Interface the MCP server binds            |
| `MCP_PORT`           | `8091`                  | Port the MCP server listens on            |

---

## 2. Tools exposed

| Tool                | Wraps                                          | Notes |
|---------------------|------------------------------------------------|-------|
| `get_meta`          | `GET /tracking/api/meta/`                      | Enums + transition graph (discovery) |
| `list_projects`     | `GET /tracking/api/projects/`                  | |
| `get_project`       | `GET /tracking/api/projects/<key>/`            | `key` uppercase, e.g. `SMT` |
| `create_project`    | `POST /tracking/api/projects/`                 | `key`, `name`, `description?` |
| `list_tickets`      | `GET /tracking/api/tickets/`                   | filter by `project` / `state` |
| `get_ticket`        | `GET /tracking/api/tickets/<id>/`              | includes `allowed_transitions` |
| `create_ticket`     | `POST /tracking/api/tickets/`                  | `project`, `title`, `type?`, `priority?`, `estimation?`, `description?` |
| `update_ticket`     | `PATCH /tracking/api/tickets/<id>/`            | fields only (incl. `estimation`); **not** `state` |
| `transition_ticket` | `POST /tracking/api/tickets/<id>/transition/`  | `state`; 409 + `allowed_transitions` if illegal |
| `list_sprints`      | `GET /tracking/api/sprints/<key>/`             | all sprints of a project |
| `get_active_sprint_tickets` | `GET /tracking/api/sprints/<key>/active/tickets/` | tickets of the project's active sprint; `sprint: null` + empty list when none is active |

State changes go **only** through `transition_ticket` (mirroring the API);
`update_ticket` rejects a `state` key. API errors are returned to the agent as
`{"status": <code>, "error": "..."}` rather than raising.

---

## 3. Connect a client

The MCP server speaks **streamable HTTP** at `http://127.0.0.1:8091/mcp`. Point
any MCP client at that URL.

### VS Code (Copilot agent mode) — `.vscode/mcp.json` in the consuming project

```json
{
  "servers": {
    "smarttracking": {
      "type": "http",
      "url": "http://127.0.0.1:8091/mcp"
    }
  }
}
```

### Claude Desktop / stdio-only clients

Bridge the HTTP endpoint to stdio with `mcp-remote`:

```json
{
  "mcpServers": {
    "smarttracking": {
      "command": "npx",
      "args": ["mcp-remote", "http://127.0.0.1:8091/mcp"]
    }
  }
}
```

Cursor, Windsurf, and Cline accept the same HTTP URL (native) or the
`mcp-remote` bridge.

---

## 4. Example agent flow

> **User:** "Open a critical bug in project SMT: login page 500s."

1. `get_meta` -> learns `type` includes `bug`, `priority` `4` = Critical.
2. `create_ticket(project="SMT", title="Login page 500s", type="bug", priority=4)`
   -> returns the ticket with its `id` and
   `allowed_transitions: ["in_progress", "closed"]`.

> **User:** "Start working on ticket 7."

3. `transition_ticket(ticket_id=7, state="in_progress")` -> success. If the move
   were illegal, the tool returns `409` + `allowed_transitions` so the agent can
   pick a valid next state.

---

## 5. Security notes

- The dev API is CSRF-exempt and served over plain HTTP with a shared bearer
  token - fine for local agent use, **not** production.
- `MCP_HOST` defaults to `127.0.0.1` (loopback only). Don't bind it to a public
  interface without adding TLS and per-user auth first.
- Treat `TRACKING_API_TOKEN` as a secret: keep it in `.env` (gitignored) or a
  secrets manager, never commit it.

