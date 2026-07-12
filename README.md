# mcp-stepik

MCP-сервер для авторства курсов на [Stepik](https://stepik.org): **FastMCP (HTTP) + Rust StateStore/TaskStore**, workflow как в [`mcp-presentation`](https://github.com/hewimetall/mcp-presentation).

## Пакеты

| Пакет | Import | Роль |
|-------|--------|------|
| **`mcp-stepik-core`** | `mcp_stepik` | FastMCP + TaskStore + CLI |
| **`mcp-stepik-state`** | `mcp_state` | sessions / workspaces (rusqlite) |

Стек: **Python 3.12+ · FastMCP · Rust 1.95 / PyO3 · rusqlite · httpx · Pydantic**.

## Happy path (workflow)

```text
create_session
  → create_project(project_id)
  → checkout_workspace(session_id, project_id)
  → save_course_ir(session_id, ir_json)   # Pydantic validate → course.ir.json
  → sync_course(session_id)               # task: IR → Stepik API
  → upload_video(session_id, "assets/a.mp4")  # task: upload + poll ready
  → get_course_page_url(session_id)       # https://stepik.org/course/{id}/
  → publish_course(session_id)            # task: is_enabled=true
```

Пример IR: [`examples/demo/course.ir.json`](examples/demo/course.ir.json)  
Schema: [`schemas/course.ir.schema.json`](schemas/course.ir.schema.json)

## Production (Docker / GHCR)

Image: [`ghcr.io/hewimetall/mcp-stepik`](https://github.com/hewimetall/mcp-stepik/pkgs/container/mcp-stepik)  
Tags: `0.1.0`, `0.1`, `0`, `latest` (built on git tag `v*`).

```bash
export STEPIK_CLIENT_ID=...
export STEPIK_CLIENT_SECRET=...

# one-shot
docker run --rm -p 8000:8000 \
  -e STEPIK_CLIENT_ID -e STEPIK_CLIENT_SECRET \
  -v mcp-stepik-data:/data \
  ghcr.io/hewimetall/mcp-stepik:0.1.0

# or compose
docker compose up -d
```

Container defaults: listen `0.0.0.0:8000`, persist under `/data` (`state`, `projects`, `workspaces`).  
MCP endpoint: `http://<host>:8000/mcp`

OAuth app: https://stepik.org/oauth2/applications/  
(`Confidential` + `Client credentials`)

If the package is private: `echo $GHCR_TOKEN | docker login ghcr.io -u USER --password-stdin`

### Cursor / HTTP MCP

```json
{
  "mcpServers": {
    "mcp-stepik": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

## Run locally (HTTP only)

```bash
uv sync --extra dev
(cd packages/mcp-stepik-state && maturin develop)
maturin develop

export STEPIK_CLIENT_ID=...
export STEPIK_CLIENT_SECRET=...
export MCP_STEPIK_HOST=127.0.0.1
export MCP_STEPIK_PORT=8000
uv run mcp-stepik
```

Env for data dirs (optional):

```bash
export MCP_STEPIK_STATE=/abs/path/state
export MCP_STEPIK_PROJECTS=/abs/path/projects
export MCP_STEPIK_WORKSPACES=/abs/path/workspaces
```

## Tools

### Workflow / state

`create_session`, `get_session`, `list_sessions`,  
`create_project`, `checkout_workspace`, `create_workspace`, `get_workspace`,  
`list_workspaces`, `set_active_workspace`, `remove_workspace`,  
`save_course_ir`, `sync_course`, `upload_video`, `publish_course`,  
`get_task_status`, `get_course_page_url`

### Stepik CRUD

Courses / sections / lessons / units / steps:  
text, choice, code, video, string, number, matching, sorting, free-answer, review  
+ `stepik_health_check`, `stepik_list_courses`, …

## Docs

- Changelog: [`CHANGELOG.md`](CHANGELOG.md)
- Architecture: [`docs/architecture/OVERVIEW.md`](docs/architecture/OVERVIEW.md)
- ADR: [`docs/adr/`](docs/adr/README.md)

## Dev

```bash
make develop
make test
make lint
make cov-rust
```

## Диск

```text
state/tasks.db  state/sessions.db
projects/<id>/
workspaces/<ws_id>/course.ir.json
```
