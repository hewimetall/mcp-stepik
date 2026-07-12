# ADR-0001: FastMCP HTTP-only transport

- Status: Accepted
- Date: 2026-07-12

## Decision

MCP server listens with `transport="http"` only (no stdio default).

Configure via `MCP_STEPIK_HOST` / `MCP_STEPIK_PORT`.

## Consequences

Clients connect to `http://host:port/mcp` (FastMCP streamable HTTP). Cursor can use URL-based MCP config.
