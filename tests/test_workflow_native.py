"""Workflow smoke with real StateStore/TaskStore (native extensions)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("mcp_state._native")
pytest.importorskip("mcp_stepik._tasks")

from mcp_state import StateStore
from mcp_stepik._tasks import TaskStore
from mcp_stepik.ir_io import write_ir
from mcp_stepik.ir_models import validate_ir_obj


def test_session_workspace_ir_flow(tmp_path: Path) -> None:
    state = StateStore(str(tmp_path / "sessions.db"))
    tasks = TaskStore(str(tmp_path / "tasks.db"))

    sid = state.create_session(meta='{"t":1}')
    proj = tmp_path / "projects" / "demo"
    proj.mkdir(parents=True)
    (proj / "project.meta.json").write_text(json.dumps({"project_id": "demo"}))

    ws = tmp_path / "workspaces" / "ws1"
    ws.mkdir(parents=True)
    wid = state.create_workspace("demo", str(ws), ref_name="main", workspace_id="ws1")
    state.set_active_workspace(sid, wid)

    ir = validate_ir_obj(
        {
            "course": {"title": "T"},
            "sections": [
                {
                    "title": "S",
                    "lessons": [
                        {"title": "L", "steps": [{"type": "text", "html": "<p>hi</p>"}]}
                    ],
                }
            ],
        }
    )
    write_ir(ws, ir)
    assert (ws / "course.ir.json").exists()

    tid = tasks.submit(sid, str(ws), "sync")
    claimed = tasks.claim_next()
    assert claimed is not None
    assert claimed["task_id"] == tid
    tasks.update(tid, status="done", artifact="42", logs="ok")
    done = tasks.get(tid)
    assert done["status"] == "done"
    assert done["artifact"] == "42"

    latest = tasks.find_latest_done(str(ws), "sync")
    assert latest is not None
    assert latest["task_id"] == tid
