"""FastMCP entrypoint — sessions/workspaces + course IR workflow + Stepik CRUD.

HTTP only (see ``main``). Happy path mirrors mcp-presentation:

  create_session
    → create_project(project_id)
    → checkout_workspace(session_id, project_id)
    → save_course_ir(session_id, ir_json)
    → sync_course(session_id)          # task: IR → Stepik API
    → upload_video(session_id, path)   # task: file → poll ready
    → get_course_page_url(session_id)
    → publish_course(session_id)       # task
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, cast

from fastmcp import FastMCP

from mcp_state import StateStore
from mcp_stepik._tasks import TaskStore
from mcp_stepik.client import StepikError, get_client
from mcp_stepik.ir_io import write_ir
from mcp_stepik.ir_models import validate_ir_json
from mcp_stepik.paths import (
    IR_FILENAME,
    META_FILENAME,
    PROJECTS_DIR,
    WORKSPACES_DIR,
    project_path,
    require_safe_id,
    workspace_path,
)
from mcp_stepik.settings import MCP_HOST, MCP_PORT, TASK_WAIT_TIMEOUT_SEC
from mcp_stepik.sync import _load_meta
from mcp_stepik.task_bridge import await_sqlite_task
from mcp_stepik.worker import wake_worker

STATE_DIR = Path(os.environ.get("MCP_STEPIK_STATE", "state"))
TASKS_DB = STATE_DIR / "tasks.db"
SESSIONS_DB = STATE_DIR / "sessions.db"

mcp = FastMCP("mcp-stepik")
_tasks: TaskStore | None = None
_state: StateStore | None = None


def get_tasks() -> TaskStore:
    global _tasks
    if _tasks is None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        _tasks = TaskStore(str(TASKS_DB))
    return _tasks


def get_state() -> StateStore:
    global _state
    if _state is None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        _state = StateStore(str(SESSIONS_DB))
    return _state


def _active_workspace(session_id: str) -> dict[str, Any]:
    session = get_state().get_session(session_id)
    if session is None:
        return {"error": "session_not_found", "session_id": session_id}
    wid = session.get("active_workspace_id")
    if not wid:
        return {"error": "no_active_workspace", "session_id": session_id}
    ws = get_state().get_workspace(wid)
    if ws is None or ws.get("status") != "active":
        return {"error": "workspace_unavailable", "workspace_id": wid}
    return {"session": session, "workspace": ws}


async def _enqueue_and_wait(session_id: str, target: str, artifact: str = "") -> dict[str, Any]:
    resolved = _active_workspace(session_id)
    if "error" in resolved:
        return resolved
    session = cast(dict[str, Any], resolved["session"])
    ws = cast(dict[str, Any], resolved["workspace"])
    path = ws["path"]
    tid = get_tasks().submit(session["session_id"], path, target)
    if artifact:
        get_tasks().update(tid, artifact=artifact)
    wake_worker(get_tasks())
    try:
        row = await await_sqlite_task(get_tasks(), tid, timeout=TASK_WAIT_TIMEOUT_SEC)
    except TimeoutError as exc:
        get_tasks().update(tid, status="error", error=str(exc))
        return {"error": "wait_timeout", "task_id": tid, "detail": str(exc)}
    return dict(row)


# ---------- sessions / workspaces (presentation workflow) ----------


@mcp.tool()
def create_session(meta: str = "") -> dict[str, Any]:
    """Create a persistent session (mcp-stepik-state)."""
    sid = get_state().create_session(meta=meta or None)
    return {"session_id": sid}


@mcp.tool()
def get_session(session_id: str) -> dict[str, Any]:
    """Read session from SQLite."""
    row = get_state().get_session(session_id)
    if row is None:
        return {"error": "not_found", "session_id": session_id}
    return dict(row)


@mcp.tool()
def list_sessions() -> dict[str, Any]:
    """List all sessions."""
    return {"sessions": [dict(r) for r in get_state().list_sessions()]}


@mcp.tool()
def create_project(project_id: str, title: str = "") -> dict[str, Any]:
    """Create on-disk project folder under projects/<id>/."""
    try:
        path = project_path(project_id)
    except ValueError as exc:
        return {"error": "invalid_id", "detail": str(exc)}
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True, exist_ok=True)
    meta = {"project_id": project_id, "title": title or project_id}
    (path / META_FILENAME).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    return {"project_id": project_id, "path": str(path.resolve())}


@mcp.tool()
def checkout_workspace(
    session_id: str,
    project_id: str,
    workspace_id: str = "",
    ref_name: str = "main",
) -> dict[str, Any]:
    """Create workspace dir, register in state, set session active."""
    session = get_state().get_session(session_id)
    if session is None:
        return {"error": "session_not_found", "session_id": session_id}
    try:
        require_safe_id(project_id, kind="project_id")
        proj = project_path(project_id)
    except ValueError as exc:
        return {"error": "invalid_id", "detail": str(exc)}
    if not proj.exists():
        return {"error": "project_not_found", "project_id": project_id}

    wid = workspace_id.strip() or uuid.uuid4().hex[:12]
    try:
        require_safe_id(wid, kind="workspace_id")
        wt = workspace_path(wid)
    except ValueError as exc:
        return {"error": "invalid_id", "detail": str(exc)}

    if get_state().get_workspace(wid) is not None:
        return {"error": "workspace_exists", "workspace_id": wid}

    WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
    wt.mkdir(parents=True, exist_ok=True)
    # seed meta from project
    proj_meta = {}
    pm = proj / META_FILENAME
    if pm.exists():
        proj_meta = json.loads(pm.read_text(encoding="utf-8"))
    (wt / META_FILENAME).write_text(
        json.dumps({**proj_meta, "project_id": project_id}, ensure_ascii=False, indent=2) + "\n"
    )

    state_wid = get_state().create_workspace(
        project_id,
        str(wt.resolve()),
        ref_name=ref_name or None,
        workspace_id=wid,
    )
    get_state().set_active_workspace(session_id, state_wid)
    return {
        "workspace_id": state_wid,
        "session_id": session_id,
        "project_id": project_id,
        "path": str(wt.resolve()),
        "ref_name": ref_name or "main",
        "note": f"workspace_id is the on-disk folder name under workspaces/; path={wt.resolve()}",
    }


@mcp.tool()
def create_workspace(project_id: str, path: str, ref_name: str = "main") -> dict[str, Any]:
    """Register an existing path in state (no checkout). Prefer checkout_workspace."""
    wid = get_state().create_workspace(project_id, path, ref_name=ref_name or None)
    return {"workspace_id": wid, "project_id": project_id, "path": path}


@mcp.tool()
def get_workspace(workspace_id: str) -> dict[str, Any]:
    row = get_state().get_workspace(workspace_id)
    if row is None:
        return {"error": "not_found", "workspace_id": workspace_id}
    return dict(row)


@mcp.tool()
def list_workspaces(project_id: str = "", status: str = "") -> dict[str, Any]:
    rows = get_state().list_workspaces(
        project_id=project_id or None,
        status=status or None,
    )
    return {"workspaces": [dict(r) for r in rows]}


@mcp.tool()
def set_active_workspace(session_id: str, workspace_id: str) -> dict[str, Any]:
    try:
        get_state().set_active_workspace(session_id, workspace_id)
    except Exception as exc:  # noqa: BLE001
        return {"error": "not_found", "detail": str(exc)}
    row = get_state().get_session(session_id)
    return dict(row) if row else {"error": "not_found", "session_id": session_id}


@mcp.tool()
def remove_workspace(workspace_id: str) -> dict[str, Any]:
    """Mark workspace removed in state (does not delete files)."""
    try:
        get_state().mark_workspace_removed(workspace_id)
    except Exception as exc:  # noqa: BLE001
        return {"error": "not_found", "detail": str(exc)}
    return {"workspace_id": workspace_id, "status": "removed"}


@mcp.tool()
def save_course_ir(session_id: str, ir_json: str) -> dict[str, Any]:
    """Validate course IR and write course.ir.json into the active workspace."""
    resolved = _active_workspace(session_id)
    if "error" in resolved:
        return resolved
    ws = cast(dict[str, Any], resolved["workspace"])
    try:
        ir = validate_ir_json(ir_json)
    except Exception as exc:  # noqa: BLE001
        return {"error": "invalid_ir", "detail": str(exc)}
    path = write_ir(Path(ws["path"]), ir)
    return {
        "path": str(path),
        "course_title": ir.course.title,
        "sections": len(ir.sections),
        "rebuild_required": True,
        "note": f"IR saved; run sync_course to push to Stepik ({IR_FILENAME})",
    }


@mcp.tool()
async def sync_course(session_id: str) -> dict[str, Any]:
    """Push course.ir.json to Stepik (async task). Waits until done/error."""
    return await _enqueue_and_wait(session_id, "sync")


@mcp.tool()
async def upload_video(session_id: str, path: str, lesson_id: int = 0) -> dict[str, Any]:
    """Upload a video file from the workspace and wait until status=ready."""
    payload = {"path": path, "lesson_id": lesson_id or None}
    return await _enqueue_and_wait(session_id, "upload_video", artifact=json.dumps(payload))


@mcp.tool()
async def publish_course(session_id: str) -> dict[str, Any]:
    """Publish the synced course (is_enabled=true). Waits on task."""
    return await _enqueue_and_wait(session_id, "publish")


@mcp.tool()
def get_task_status(task_id: str) -> dict[str, Any]:
    """Inspect a TaskStore row."""
    row = get_tasks().get(task_id)
    if row is None:
        return {"error": "not_found", "task_id": task_id}
    return dict(row)


@mcp.tool()
def get_course_page_url(session_id: str) -> dict[str, Any]:
    """Return Stepik course page / edit URLs for the active workspace."""
    resolved = _active_workspace(session_id)
    if "error" in resolved:
        return resolved
    ws = cast(dict[str, Any], resolved["workspace"])
    meta = _load_meta(Path(ws["path"]))
    course_id = meta.get("course_id")
    if not course_id:
        return {"error": "no_course_id", "detail": "sync_course first"}
    return {
        "course_id": course_id,
        "url": f"https://stepik.org/course/{course_id}/",
        "edit_url": f"https://stepik.org/course/{course_id}/edit",
        "promo_url": f"https://stepik.org/course/{course_id}/promo",
    }


# ---------- fine-grained Stepik CRUD ----------


@mcp.tool()
def stepik_health_check() -> dict[str, Any]:
    """Verify OAuth against Stepik API."""
    try:
        return get_client().health()
    except StepikError as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def stepik_list_courses(page: int = 1) -> dict[str, Any]:
    """List courses you own."""
    try:
        data = get_client().list_my_courses(page=page)
    except StepikError as exc:
        return {"error": str(exc)}
    courses = [
        {
            "id": c["id"],
            "title": c["title"],
            "is_enabled": c.get("is_enabled"),
            "learners_count": c.get("learners_count", 0),
            "url": f"https://stepik.org/course/{c['id']}/",
        }
        for c in data.get("courses") or []
    ]
    return {"courses": courses, "meta": data.get("meta")}


@mcp.tool()
def stepik_get_course(course_id: int) -> dict[str, Any]:
    try:
        c = get_client().get_course(course_id)
    except StepikError as exc:
        return {"error": str(exc)}
    return {
        "id": c["id"],
        "title": c["title"],
        "summary": c.get("summary", ""),
        "is_enabled": c.get("is_enabled"),
        "sections": c.get("sections"),
        "url": f"https://stepik.org/course/{c['id']}/",
        "edit_url": f"https://stepik.org/course/{c['id']}/edit",
    }


@mcp.tool()
def stepik_create_course(title: str, summary: str = "") -> dict[str, Any]:
    try:
        c = get_client().create_course(title, summary=summary)
    except StepikError as exc:
        return {"error": str(exc)}
    return {
        "id": c["id"],
        "title": c["title"],
        "url": f"https://stepik.org/course/{c['id']}/",
        "edit_url": f"https://stepik.org/course/{c['id']}/edit",
    }


@mcp.tool()
def stepik_update_course(
    course_id: int,
    title: str = "",
    summary: str = "",
    description: str = "",
    is_enabled: bool | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if title:
        fields["title"] = title
    if summary:
        fields["summary"] = summary
    if description:
        fields["description"] = description
    if is_enabled is not None:
        fields["is_enabled"] = is_enabled
    if not fields:
        return {"error": "nothing_to_update"}
    try:
        c = get_client().update_course(course_id, **fields)
    except StepikError as exc:
        return {"error": str(exc)}
    return {"id": c["id"], "title": c["title"], "is_enabled": c.get("is_enabled")}


@mcp.tool()
def stepik_create_section(course_id: int, title: str, position: int = 1) -> dict[str, Any]:
    try:
        s = get_client().create_section(course_id, title, position=position)
    except StepikError as exc:
        return {"error": str(exc)}
    return {"id": s["id"], "title": s["title"], "course": s.get("course")}


@mcp.tool()
def stepik_update_section(
    section_id: int, title: str = "", position: int | None = None
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if title:
        fields["title"] = title
    if position is not None:
        fields["position"] = position
    try:
        s = get_client().update_section(section_id, **fields)
    except StepikError as exc:
        return {"error": str(exc)}
    return {"id": s["id"], "title": s["title"]}


@mcp.tool()
def stepik_delete_section(section_id: int) -> dict[str, Any]:
    try:
        get_client().delete_section(section_id)
    except StepikError as exc:
        return {"error": str(exc)}
    return {"deleted": section_id}


@mcp.tool()
def stepik_get_sections(course_id: int) -> dict[str, Any]:
    try:
        sections = get_client().list_sections(course_id)
    except StepikError as exc:
        return {"error": str(exc)}
    return {
        "sections": [
            {"id": s["id"], "title": s["title"], "position": s.get("position"), "units": s.get("units")}
            for s in sections
        ]
    }


@mcp.tool()
def stepik_create_lesson(title: str, is_public: bool = False) -> dict[str, Any]:
    try:
        les = get_client().create_lesson(title, is_public=is_public)
    except StepikError as exc:
        return {"error": str(exc)}
    return {"id": les["id"], "title": les["title"]}


@mcp.tool()
def stepik_update_lesson(
    lesson_id: int, title: str = "", is_public: bool | None = None
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if title:
        fields["title"] = title
    if is_public is not None:
        fields["is_public"] = is_public
    try:
        les = get_client().update_lesson(lesson_id, **fields)
    except StepikError as exc:
        return {"error": str(exc)}
    return {"id": les["id"], "title": les["title"]}


@mcp.tool()
def stepik_delete_lesson(lesson_id: int) -> dict[str, Any]:
    try:
        get_client().delete_lesson(lesson_id)
    except StepikError as exc:
        return {"error": str(exc)}
    return {"deleted": lesson_id}


@mcp.tool()
def stepik_create_unit(section_id: int, lesson_id: int, position: int = 1) -> dict[str, Any]:
    try:
        u = get_client().create_unit(section_id, lesson_id, position=position)
    except StepikError as exc:
        return {"error": str(exc)}
    return {"id": u["id"], "section": u.get("section"), "lesson": u.get("lesson")}


@mcp.tool()
def stepik_get_steps(lesson_id: int) -> dict[str, Any]:
    try:
        steps = get_client().list_steps(lesson_id)
    except StepikError as exc:
        return {"error": str(exc)}
    return {
        "steps": [
            {
                "id": s["id"],
                "position": s.get("position"),
                "type": (s.get("block") or {}).get("name"),
            }
            for s in steps
        ]
    }


@mcp.tool()
def stepik_create_text_step(lesson_id: int, text_html: str, position: int = 1) -> dict[str, Any]:
    try:
        s = get_client().create_step_source(
            {
                "lesson": lesson_id,
                "position": position,
                "block": {"name": "text", "text": text_html},
            }
        )
    except StepikError as exc:
        return {"error": str(exc)}
    return {"id": s["id"], "lesson": lesson_id, "position": position}


@mcp.tool()
def stepik_create_choice_step(
    lesson_id: int,
    question: str,
    choices_json: str,
    correct_indices_json: str,
    position: int = 1,
) -> dict[str, Any]:
    """choices_json: JSON list of strings. correct_indices_json: JSON list of 0-based ints."""
    try:
        choices = json.loads(choices_json)
        correct = set(json.loads(correct_indices_json))
        options = [
            {"text": c, "is_correct": i in correct, "feedback": ""} for i, c in enumerate(choices)
        ]
        s = get_client().create_step_source(
            {
                "lesson": lesson_id,
                "position": position,
                "block": {
                    "name": "choice",
                    "text": question,
                    "source": {
                        "options": options,
                        "is_always_correct": False,
                        "is_html_enabled": True,
                        "preserve_order": False,
                        "is_multiple_choice": len(correct) > 1,
                        "sample_size": len(choices),
                    },
                },
            }
        )
    except (StepikError, json.JSONDecodeError, TypeError) as exc:
        return {"error": str(exc)}
    return {"id": s["id"], "lesson": lesson_id}


@mcp.tool()
def stepik_create_code_step(
    lesson_id: int,
    text: str,
    language: str = "python3",
    templates_data: str = "",
    test_cases_json: str = "[]",
    position: int = 1,
) -> dict[str, Any]:
    try:
        tests = json.loads(test_cases_json)
        s = get_client().create_step_source(
            {
                "lesson": lesson_id,
                "position": position,
                "block": {
                    "name": "code",
                    "text": text,
                    "source": {
                        "language": language,
                        "templates_data": templates_data,
                        "test_cases": tests,
                        "is_time_limit": False,
                        "is_memory_limit": False,
                    },
                },
            }
        )
    except (StepikError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}
    return {"id": s["id"], "lesson": lesson_id}


@mcp.tool()
def stepik_create_video_step(
    lesson_id: int, video_id: int, text: str = "", position: int = 1
) -> dict[str, Any]:
    """Attach an already-uploaded ready video to a lesson."""
    try:
        s = get_client().create_step_source(
            {
                "lesson": lesson_id,
                "position": position,
                "block": {"name": "video", "text": text, "video": video_id},
            }
        )
    except StepikError as exc:
        return {"error": str(exc)}
    return {"id": s["id"], "lesson": lesson_id, "video_id": video_id}


@mcp.tool()
def stepik_create_string_step(
    lesson_id: int, text: str, pattern: str, case_sensitive: bool = False, position: int = 1
) -> dict[str, Any]:
    try:
        s = get_client().create_step_source(
            {
                "lesson": lesson_id,
                "position": position,
                "block": {
                    "name": "string",
                    "text": text,
                    "source": {"pattern": pattern, "case_sensitive": case_sensitive},
                },
            }
        )
    except StepikError as exc:
        return {"error": str(exc)}
    return {"id": s["id"]}


@mcp.tool()
def stepik_create_number_step(
    lesson_id: int, text: str, answer: float, max_error: float = 0.0, position: int = 1
) -> dict[str, Any]:
    try:
        s = get_client().create_step_source(
            {
                "lesson": lesson_id,
                "position": position,
                "block": {
                    "name": "number",
                    "text": text,
                    "source": {
                        "options": [{"answer": str(answer), "max_error": str(max_error)}]
                    },
                },
            }
        )
    except StepikError as exc:
        return {"error": str(exc)}
    return {"id": s["id"]}


@mcp.tool()
def stepik_create_matching_step(
    lesson_id: int, text: str, pairs_json: str, position: int = 1
) -> dict[str, Any]:
    """pairs_json: [{"first":"...","second":"..."}, ...]"""
    try:
        pairs = json.loads(pairs_json)
        s = get_client().create_step_source(
            {
                "lesson": lesson_id,
                "position": position,
                "block": {"name": "matching", "text": text, "source": {"pairs": pairs}},
            }
        )
    except (StepikError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}
    return {"id": s["id"]}


@mcp.tool()
def stepik_create_sorting_step(
    lesson_id: int, text: str, items_json: str, position: int = 1
) -> dict[str, Any]:
    """items_json: JSON list of strings in correct order."""
    try:
        items = json.loads(items_json)
        s = get_client().create_step_source(
            {
                "lesson": lesson_id,
                "position": position,
                "block": {
                    "name": "sorting",
                    "text": text,
                    "source": {"options": [{"text": i} for i in items]},
                },
            }
        )
    except (StepikError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}
    return {"id": s["id"]}


@mcp.tool()
def stepik_create_free_answer_step(lesson_id: int, text: str, position: int = 1) -> dict[str, Any]:
    try:
        s = get_client().create_step_source(
            {
                "lesson": lesson_id,
                "position": position,
                "block": {"name": "free-answer", "text": text, "source": {}},
            }
        )
    except StepikError as exc:
        return {"error": str(exc)}
    return {"id": s["id"]}


@mcp.tool()
def stepik_create_review_step(
    lesson_id: int, text: str, instructions_to_reviewer: str = "", position: int = 1
) -> dict[str, Any]:
    try:
        s = get_client().create_step_source(
            {
                "lesson": lesson_id,
                "position": position,
                "block": {
                    "name": "review",
                    "text": text,
                    "source": {"instructions_to_reviewer": instructions_to_reviewer},
                },
            }
        )
    except StepikError as exc:
        return {"error": str(exc)}
    return {"id": s["id"]}


def main() -> None:
    """HTTP-only MCP server."""
    mcp.run(transport="http", host=MCP_HOST, port=MCP_PORT)


if __name__ == "__main__":
    main()
