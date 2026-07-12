# Changelog

## [0.1.0] — 2026-07-12

First release.

### Added

- FastMCP HTTP server for Stepik course authoring (`mcp-stepik-core`)
- Rust `StateStore` (sessions / workspaces) and `TaskStore` (async sync / video / publish)
- Course IR (`course.ir.json`) + schema and demo example
- Workflow tools: session → project → workspace → save IR → sync / video / publish
- Stepik CRUD tools for courses, sections, lessons, units, and common step types
- Docker image published to GHCR on version tags (`ghcr.io/hewimetall/mcp-stepik`)

### Notes

- Transport: HTTP only (default `0.0.0.0:8000` in the container)
- OAuth: Stepik Confidential app with **Client credentials**
- Publish may fail on accounts without the required Stepik plan/permissions
