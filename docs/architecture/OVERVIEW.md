# Architecture overview — mcp-stepik

```text
                    ┌─────────────────────────────┐
                    │     FastMCP (Python) HTTP   │
                    │  mcp-stepik-core            │
                    │  + SyncWorker + Course IR   │
                    └──────────────┬──────────────┘
           ┌───────────────────────┼───────────────────────┐
           ▼                       ▼                       ▼
   ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
   │ mcp-stepik-state│    │ TaskStore       │    │ StepikClient    │
   │ StateStore      │    │ (rusqlite)      │    │ httpx / OAuth2  │
   │ (rusqlite)      │    │                 │    │                 │
   └────────┬────────┘    └────────┬────────┘    └────────┬────────┘
            ▼                      ▼                      ▼
    state/sessions.db       state/tasks.db         stepik.org/api
    workspaces/*/
    projects/*/
```

## Packages

| Package | Role | Persistence |
|---------|------|-------------|
| `mcp-stepik-core` | FastMCP + TaskStore + worker | `state/tasks.db` |
| `mcp-stepik-state` | sessions / workspaces | `state/sessions.db` |

## Workflow (как presentation)

```text
create_session
  → create_project(project_id)
  → checkout_workspace(session_id, project_id)
  → save_course_ir(session_id, ir_json)
  → sync_course(session_id)            # task → Stepik API
  → upload_video(session_id, path)     # task → poll status=ready
  → get_course_page_url(session_id)
  → publish_course(session_id)         # task
```

## Task targets

| target | meaning |
|--------|---------|
| `sync` | IR → create/update course structure |
| `upload_video` | multipart upload + poll `ready` |
| `publish` | `is_enabled=true` |

Statuses: `queued` → `running` → `done` | `error`

## Transport

**HTTP only** — `mcp.run(transport="http")`.  
Env: `MCP_STEPIK_HOST` (default `127.0.0.1`), `MCP_STEPIK_PORT` (default `8000`).
