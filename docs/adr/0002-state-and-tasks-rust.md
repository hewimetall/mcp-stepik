# ADR-0002: Separate Rust state + TaskStore

- Status: Accepted
- Date: 2026-07-12
- Relates: mcp-presentation ADR-0004 / ADR-0010

## Decision

Mirror presentation packaging:

| Package | Class | DB |
|---------|-------|-----|
| `mcp-stepik-state` | `StateStore` | `sessions.db` |
| `mcp-stepik-core` | `TaskStore` | `tasks.db` |

Both PyO3 + rusqlite.

## Consequences

Same session/workspace UX as presentation; video/sync/publish use durable tasks.
