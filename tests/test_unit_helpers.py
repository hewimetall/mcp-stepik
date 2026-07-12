"""Unit tests for paths, IR, sync helpers (no live Stepik)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_stepik.ir_io import read_ir, write_ir
from mcp_stepik.ir_models import (
    ChoiceStep,
    TextStep,
    parse_step,
    step_to_block,
    validate_ir_json,
    validate_ir_obj,
)
from mcp_stepik.paths import project_path, require_safe_id, workspace_path


def test_require_safe_id() -> None:
    assert require_safe_id("abc-1") == "abc-1"
    with pytest.raises(ValueError):
        require_safe_id("../x")


def test_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_STEPIK_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("MCP_STEPIK_WORKSPACES", str(tmp_path / "workspaces"))
    import importlib

    import mcp_stepik.paths as paths

    importlib.reload(paths)
    assert paths.project_path("p1").name == "p1"
    assert paths.workspace_path("w1").name == "w1"


def test_validate_demo_ir() -> None:
    raw = Path("examples/demo/course.ir.json").read_text(encoding="utf-8")
    ir = validate_ir_json(raw)
    assert ir.course.title.startswith("Demo")
    assert ir.sections[0].lessons[0].steps


def test_parse_and_block_types() -> None:
    text = parse_step({"type": "text", "html": "<p>x</p>"})
    assert isinstance(text, TextStep)
    assert step_to_block(text)["name"] == "text"

    choice = parse_step(
        {
            "type": "choice",
            "question": "q",
            "options": [{"text": "a", "is_correct": True}],
        }
    )
    assert isinstance(choice, ChoiceStep)
    block = step_to_block(choice)
    assert block["name"] == "choice"
    assert block["source"]["options"][0]["is_correct"] is True

    code = parse_step({"type": "code", "text": "t", "language": "python3"})
    assert step_to_block(code)["name"] == "code"

    video = parse_step({"type": "video", "video_id": 1})
    assert step_to_block(video)["video"] == 1

    with pytest.raises(ValueError):
        step_to_block(parse_step({"type": "video", "path": "a.mp4"}))

    assert step_to_block(parse_step({"type": "string", "text": "t", "pattern": "x"}))["name"] == "string"
    assert step_to_block(parse_step({"type": "number", "text": "t", "answer": 1.0}))["name"] == "number"
    assert (
        step_to_block(
            parse_step({"type": "matching", "pairs": [{"first": "a", "second": "b"}]})
        )["name"]
        == "matching"
    )
    assert step_to_block(parse_step({"type": "sorting", "items": ["a", "b"]}))["name"] == "sorting"
    assert step_to_block(parse_step({"type": "free-answer", "text": "t"}))["name"] == "free-answer"
    assert step_to_block(parse_step({"type": "review", "text": "t"}))["name"] == "review"

    with pytest.raises(ValueError):
        parse_step({"type": "unknown"})


def test_write_read_ir(tmp_path: Path) -> None:
    ir = validate_ir_obj(
        {
            "course": {"title": "T"},
            "sections": [{"title": "S", "lessons": [{"title": "L", "steps": [{"type": "text", "html": "h"}]}]}],
        }
    )
    path = write_ir(tmp_path, ir)
    assert path.name == "course.ir.json"
    loaded = read_ir(tmp_path)
    assert loaded.course.title == "T"


def test_client_auth_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_stepik.client import StepikClient, StepikError

    monkeypatch.setattr("mcp_stepik.client.STEPIK_CLIENT_ID", "")
    monkeypatch.setattr("mcp_stepik.client.STEPIK_CLIENT_SECRET", "")
    c = StepikClient(client_id="", client_secret="")
    with pytest.raises(StepikError):
        c._get_token()


def test_sync_meta(tmp_path: Path) -> None:
    from mcp_stepik.sync import _load_meta, _save_meta

    assert _load_meta(tmp_path) == {}
    _save_meta(tmp_path, {"course_id": 9})
    assert _load_meta(tmp_path)["course_id"] == 9


def test_task_bridge_done() -> None:
    import asyncio

    from mcp_stepik.task_bridge import await_sqlite_task

    class Stub:
        def get(self, task_id: str) -> dict[str, str]:
            return {"task_id": task_id, "status": "done", "artifact": "1"}

    row = asyncio.run(await_sqlite_task(Stub(), "t1", timeout=1))
    assert row["status"] == "done"


def test_worker_unknown_target(tmp_path: Path) -> None:
    from mcp_stepik.client import StepikClient, StepikError
    from mcp_stepik.worker import SyncWorker

    class FakeTasks:
        pass

    w = SyncWorker(FakeTasks(), client=StepikClient(client_id="x", client_secret="y"))
    with pytest.raises(StepikError):
        w._run(w._client, "nope", tmp_path, {})  # type: ignore[arg-type]
