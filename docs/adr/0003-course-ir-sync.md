# ADR-0003: Course IR + async sync / video / publish

- Status: Accepted
- Date: 2026-07-12

## Context

AI authors content offline as JSON (IR), then pushes to Stepik. Video upload is async (`status` until `ready`).

## Decision

- `course.ir.json` validated by Pydantic
- `sync_course` / `upload_video` / `publish_course` enqueue TaskStore jobs; tools wait
- Fine-grained `stepik_*` tools remain for surgical edits

## Consequences

Happy path matches presentation build/deploy; Stepik-specific async is video processing.
