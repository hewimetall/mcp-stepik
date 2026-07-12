"""Push Course IR to Stepik API (create/update structure)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp_stepik.client import StepikClient, StepikError
from mcp_stepik.ir_io import read_ir, write_ir
from mcp_stepik.ir_models import VideoStep, step_to_block
from mcp_stepik.paths import META_FILENAME
from mcp_stepik.settings import VIDEO_POLL_INTERVAL_SEC, VIDEO_POLL_TIMEOUT_SEC


def _load_meta(workspace: Path) -> dict[str, Any]:
    path = workspace / META_FILENAME
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_meta(workspace: Path, meta: dict[str, Any]) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / META_FILENAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sync_course_ir(client: StepikClient, workspace: Path) -> dict[str, Any]:
    """Create/update course from course.ir.json. Returns summary with course_id."""
    ir = read_ir(workspace)
    meta = _load_meta(workspace)
    logs: list[str] = []

    course_id = ir.course.course_id or meta.get("course_id")
    if course_id is None:
        course = client.create_course(
            ir.course.title,
            summary=ir.course.summary,
            description=ir.course.description,
            language=ir.course.language,
        )
        course_id = course["id"]
        logs.append(f"created course {course_id}")
    else:
        client.update_course(
            int(course_id),
            title=ir.course.title,
            summary=ir.course.summary,
            description=ir.course.description,
            language=ir.course.language,
        )
        logs.append(f"updated course {course_id}")

    ir.course.course_id = int(course_id)
    write_ir(workspace, ir)
    meta["course_id"] = int(course_id)
    meta["title"] = ir.course.title
    _save_meta(workspace, meta)

    # naive rebuild: create missing sections/lessons/steps by position
    existing_sections = client.list_sections(int(course_id))
    for s_idx, sec in enumerate(ir.sections, start=1):
        if s_idx <= len(existing_sections):
            section = existing_sections[s_idx - 1]
            client.update_section(section["id"], title=sec.title, position=s_idx)
            section_id = section["id"]
            logs.append(f"updated section {section_id}")
        else:
            section = client.create_section(int(course_id), sec.title, position=s_idx)
            section_id = section["id"]
            logs.append(f"created section {section_id}")

        units = client.list_units(section_id)
        for l_idx, les in enumerate(sec.lessons, start=1):
            if l_idx <= len(units):
                lesson_id = units[l_idx - 1]["lesson"]
                client.update_lesson(lesson_id, title=les.title, is_public=les.is_public)
                logs.append(f"updated lesson {lesson_id}")
            else:
                lesson = client.create_lesson(les.title, is_public=les.is_public)
                lesson_id = lesson["id"]
                client.create_unit(section_id, lesson_id, position=l_idx)
                logs.append(f"created lesson {lesson_id} + unit")

            existing_steps = client.list_steps(lesson_id)
            for st_idx, step in enumerate(les.steps, start=1):
                if isinstance(step, VideoStep) and step.video_id is None and step.path:
                    raise StepikError(
                        f"video step at section={s_idx} lesson={l_idx} pos={st_idx} "
                        f"has path={step.path!r} but no video_id — run upload_video first"
                    )
                block = step_to_block(step)
                payload = {"lesson": lesson_id, "position": st_idx, "block": block}
                if st_idx <= len(existing_steps):
                    # Stepik updates go through step-sources with step id
                    sid = existing_steps[st_idx - 1]["id"]
                    client.update_step_source(sid, {"block": block})
                    logs.append(f"updated step {sid}")
                else:
                    created = client.create_step_source(payload)
                    logs.append(f"created step-source {created.get('id')}")

    return {
        "course_id": int(course_id),
        "url": f"https://stepik.org/course/{course_id}/",
        "edit_url": f"https://stepik.org/course/{course_id}/edit",
        "logs": "\n".join(logs),
    }


def wait_video_ready(client: StepikClient, video_id: int) -> dict[str, Any]:
    import time

    deadline = time.time() + VIDEO_POLL_TIMEOUT_SEC
    while time.time() < deadline:
        video = client.get_video(video_id)
        status = video.get("status")
        if status == "ready":
            return video
        if status in {"error", "failed"}:
            raise StepikError(f"video {video_id} failed: {video}")
        time.sleep(VIDEO_POLL_INTERVAL_SEC)
    raise StepikError(f"video {video_id} not ready within {VIDEO_POLL_TIMEOUT_SEC}s")


def upload_video_file(
    client: StepikClient,
    workspace: Path,
    relative_path: str,
    *,
    lesson_id: int | None = None,
) -> dict[str, Any]:
    path = (workspace / relative_path).resolve()
    if not str(path).startswith(str(workspace.resolve())):
        raise StepikError("video path escapes workspace")
    if not path.is_file():
        raise StepikError(f"video file not found: {path}")
    meta = _load_meta(workspace)
    course_id = meta.get("course_id")
    video = client.upload_video(path, lesson_id=lesson_id, course_id=course_id)
    video = wait_video_ready(client, int(video["id"]))
    return video
