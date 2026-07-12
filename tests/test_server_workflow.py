"""Exercise FastMCP workflow tools with mocked Stepik + real native stores."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp_state._native")
pytest.importorskip("mcp_stepik._tasks")

import mcp_stepik.server as server
from mcp_stepik.client import StepikClient, StepikError


@pytest.fixture()
def env_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    projects = tmp_path / "projects"
    workspaces = tmp_path / "workspaces"
    state.mkdir()
    projects.mkdir()
    workspaces.mkdir()
    monkeypatch.setenv("MCP_STEPIK_STATE", str(state))
    monkeypatch.setenv("MCP_STEPIK_PROJECTS", str(projects))
    monkeypatch.setenv("MCP_STEPIK_WORKSPACES", str(workspaces))
    # reset singletons
    server._tasks = None
    server._state = None
    server.STATE_DIR = state
    server.TASKS_DB = state / "tasks.db"
    server.SESSIONS_DB = state / "sessions.db"
    import mcp_stepik.paths as paths

    paths.PROJECTS_DIR = projects
    paths.WORKSPACES_DIR = workspaces
    return tmp_path


def test_session_project_checkout_save_ir(env_dirs: Path) -> None:
    created = server.create_session(meta='{"x":1}')
    sid = created["session_id"]
    assert server.get_session(sid)["session_id"] == sid
    assert server.list_sessions()["sessions"]

    proj = server.create_project("demo", title="Demo")
    assert Path(proj["path"]).exists()

    ws = server.checkout_workspace(sid, "demo", workspace_id="wsdemo")
    assert ws["workspace_id"] == "wsdemo"
    assert server.get_workspace("wsdemo")["status"] == "active"
    assert server.list_workspaces(project_id="demo")["workspaces"]

    ir = {
        "course": {"title": "T"},
        "sections": [
            {"title": "S", "lessons": [{"title": "L", "steps": [{"type": "text", "html": "h"}]}]}
        ],
    }
    saved = server.save_course_ir(sid, json.dumps(ir))
    assert saved.get("rebuild_required") is True
    assert Path(saved["path"]).exists()

    url = server.get_course_page_url(sid)
    assert url["error"] == "no_course_id"

    server.set_active_workspace(sid, "wsdemo")
    server.remove_workspace("wsdemo")
    assert server.get_workspace("wsdemo")["status"] == "removed"


def test_checkout_errors(env_dirs: Path) -> None:
    assert server.checkout_workspace("missing", "p")["error"] == "session_not_found"
    sid = server.create_session()["session_id"]
    assert server.checkout_workspace(sid, "nope")["error"] == "project_not_found"
    server.create_project("p1")
    assert server.create_project("../bad")["error"] == "invalid_id"


def test_create_workspace_register(env_dirs: Path) -> None:
    p = env_dirs / "external"
    p.mkdir()
    wid = server.create_workspace("proj", str(p))["workspace_id"]
    assert server.get_workspace(wid)["path"] == str(p)


def test_task_status_missing(env_dirs: Path) -> None:
    assert server.get_task_status("nope")["error"] == "not_found"


def test_enqueue_and_wait_sync(env_dirs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sid = server.create_session()["session_id"]
    server.create_project("p")
    server.checkout_workspace(sid, "p", workspace_id="w")
    server.save_course_ir(
        sid,
        json.dumps(
            {
                "course": {"title": "T"},
                "sections": [{"title": "S", "lessons": [{"title": "L", "steps": []}]}],
            }
        ),
    )

    class FakeClient:
        def create_course(self, title: str, **fields: Any) -> dict[str, Any]:
            return {"id": 99, "title": title}

        def update_course(self, course_id: int, **fields: Any) -> dict[str, Any]:
            return {"id": course_id, **fields}

        def list_sections(self, course_id: int) -> list[dict[str, Any]]:
            return []

        def create_section(self, course_id: int, title: str, position: int = 1) -> dict[str, Any]:
            return {"id": 1, "title": title, "course": course_id}

        def update_section(self, section_id: int, **fields: Any) -> dict[str, Any]:
            return {"id": section_id, **fields}

        def list_units(self, section_id: int) -> list[dict[str, Any]]:
            return []

        def create_lesson(self, title: str, is_public: bool = False) -> dict[str, Any]:
            return {"id": 10, "title": title}

        def update_lesson(self, lesson_id: int, **fields: Any) -> dict[str, Any]:
            return {"id": lesson_id, **fields}

        def create_unit(self, section_id: int, lesson_id: int, position: int = 1) -> dict[str, Any]:
            return {"id": 100, "section": section_id, "lesson": lesson_id}

        def list_steps(self, lesson_id: int) -> list[dict[str, Any]]:
            return []

        def create_step_source(self, payload: dict[str, Any]) -> dict[str, Any]:
            return {"id": 1000}

        def update_step_source(self, step_source_id: int, payload: dict[str, Any]) -> dict[str, Any]:
            return {"id": step_source_id}

        def publish_course(self, course_id: int) -> dict[str, Any]:
            return {"id": course_id, "is_enabled": True}

    monkeypatch.setattr(server, "get_client", lambda: FakeClient())
    monkeypatch.setattr("mcp_stepik.worker.get_client", lambda: FakeClient())

    # reset worker singleton
    import mcp_stepik.worker as worker

    worker._worker = None

    row = asyncio.run(server.sync_course(sid))
    assert row.get("status") == "done"
    assert row.get("artifact") == "99"

    url = server.get_course_page_url(sid)
    assert url["course_id"] == 99
    assert "stepik.org/course/99" in url["url"]

    pub = asyncio.run(server.publish_course(sid))
    assert pub.get("status") == "done"


def test_stepik_crud_wrappers(monkeypatch: pytest.MonkeyPatch) -> None:
    class C:
        def health(self) -> dict[str, Any]:
            return {"ok": True}

        def list_my_courses(self, page: int = 1) -> dict[str, Any]:
            return {"courses": [{"id": 1, "title": "A", "is_enabled": True}], "meta": {}}

        def get_course(self, course_id: int) -> dict[str, Any]:
            return {"id": course_id, "title": "A", "sections": []}

        def create_course(self, title: str, **kw: Any) -> dict[str, Any]:
            return {"id": 2, "title": title}

        def update_course(self, course_id: int, **kw: Any) -> dict[str, Any]:
            return {"id": course_id, "title": kw.get("title", "A"), "is_enabled": kw.get("is_enabled")}

        def create_section(self, course_id: int, title: str, position: int = 1) -> dict[str, Any]:
            return {"id": 3, "title": title, "course": course_id}

        def update_section(self, section_id: int, **kw: Any) -> dict[str, Any]:
            return {"id": section_id, "title": kw.get("title", "S")}

        def delete_section(self, section_id: int) -> None:
            return None

        def list_sections(self, course_id: int) -> list[dict[str, Any]]:
            return [{"id": 3, "title": "S", "position": 1, "units": []}]

        def create_lesson(self, title: str, is_public: bool = False) -> dict[str, Any]:
            return {"id": 4, "title": title}

        def update_lesson(self, lesson_id: int, **kw: Any) -> dict[str, Any]:
            return {"id": lesson_id, "title": kw.get("title", "L")}

        def delete_lesson(self, lesson_id: int) -> None:
            return None

        def create_unit(self, section_id: int, lesson_id: int, position: int = 1) -> dict[str, Any]:
            return {"id": 5, "section": section_id, "lesson": lesson_id}

        def list_steps(self, lesson_id: int) -> list[dict[str, Any]]:
            return [{"id": 6, "position": 1, "block": {"name": "text"}}]

        def create_step_source(self, payload: dict[str, Any]) -> dict[str, Any]:
            return {"id": 7}

    monkeypatch.setattr(server, "get_client", lambda: C())
    assert server.stepik_health_check()["ok"] is True
    assert server.stepik_list_courses()["courses"][0]["id"] == 1
    assert server.stepik_get_course(1)["id"] == 1
    assert server.stepik_create_course("X")["id"] == 2
    assert server.stepik_update_course(2, title="Y")["id"] == 2
    assert server.stepik_create_section(2, "S")["id"] == 3
    assert server.stepik_update_section(3, title="S2")["id"] == 3
    assert server.stepik_delete_section(3)["deleted"] == 3
    assert server.stepik_get_sections(2)["sections"]
    assert server.stepik_create_lesson("L")["id"] == 4
    assert server.stepik_update_lesson(4, title="L2")["id"] == 4
    assert server.stepik_delete_lesson(4)["deleted"] == 4
    assert server.stepik_create_unit(3, 4)["id"] == 5
    assert server.stepik_get_steps(4)["steps"]
    assert server.stepik_create_text_step(4, "<p>x</p>")["id"] == 7
    assert server.stepik_create_choice_step(4, "q", '["a","b"]', "[1]")["id"] == 7
    assert server.stepik_create_code_step(4, "t")["id"] == 7
    assert server.stepik_create_video_step(4, 9)["id"] == 7
    assert server.stepik_create_string_step(4, "t", "pat")["id"] == 7
    assert server.stepik_create_number_step(4, "t", 1.0)["id"] == 7
    assert server.stepik_create_matching_step(4, "t", '[{"first":"a","second":"b"}]')["id"] == 7
    assert server.stepik_create_sorting_step(4, "t", '["a","b"]')["id"] == 7
    assert server.stepik_create_free_answer_step(4, "t")["id"] == 7
    assert server.stepik_create_review_step(4, "t")["id"] == 7


def test_stepik_health_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class Bad:
        def health(self) -> dict[str, Any]:
            raise StepikError("boom")

    monkeypatch.setattr(server, "get_client", lambda: Bad())
    assert server.stepik_health_check()["ok"] is False


def test_main_binds_http(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> None:
        called.update(kwargs)

    monkeypatch.setattr(server.mcp, "run", fake_run)
    server.main()
    assert called.get("transport") == "http"


def test_stepik_crud_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class Boom:
        def health(self) -> dict[str, Any]:
            raise StepikError("x")

        def list_my_courses(self, page: int = 1) -> dict[str, Any]:
            raise StepikError("x")

        def get_course(self, course_id: int) -> dict[str, Any]:
            raise StepikError("x")

        def create_course(self, title: str, **kw: Any) -> dict[str, Any]:
            raise StepikError("x")

        def update_course(self, course_id: int, **kw: Any) -> dict[str, Any]:
            raise StepikError("x")

        def create_section(self, course_id: int, title: str, position: int = 1) -> dict[str, Any]:
            raise StepikError("x")

        def update_section(self, section_id: int, **kw: Any) -> dict[str, Any]:
            raise StepikError("x")

        def delete_section(self, section_id: int) -> None:
            raise StepikError("x")

        def list_sections(self, course_id: int) -> list[dict[str, Any]]:
            raise StepikError("x")

        def create_lesson(self, title: str, is_public: bool = False) -> dict[str, Any]:
            raise StepikError("x")

        def update_lesson(self, lesson_id: int, **kw: Any) -> dict[str, Any]:
            raise StepikError("x")

        def delete_lesson(self, lesson_id: int) -> None:
            raise StepikError("x")

        def create_unit(self, section_id: int, lesson_id: int, position: int = 1) -> dict[str, Any]:
            raise StepikError("x")

        def list_steps(self, lesson_id: int) -> list[dict[str, Any]]:
            raise StepikError("x")

        def create_step_source(self, payload: dict[str, Any]) -> dict[str, Any]:
            raise StepikError("x")

    monkeypatch.setattr(server, "get_client", lambda: Boom())
    assert "error" in server.stepik_list_courses()
    assert "error" in server.stepik_get_course(1)
    assert "error" in server.stepik_create_course("t")
    assert "error" in server.stepik_update_course(1, title="t")
    assert "error" in server.stepik_create_section(1, "s")
    assert "error" in server.stepik_update_section(1, title="s")
    assert "error" in server.stepik_delete_section(1)
    assert "error" in server.stepik_get_sections(1)
    assert "error" in server.stepik_create_lesson("l")
    assert "error" in server.stepik_update_lesson(1, title="l")
    assert "error" in server.stepik_delete_lesson(1)
    assert "error" in server.stepik_create_unit(1, 2)
    assert "error" in server.stepik_get_steps(1)
    assert "error" in server.stepik_create_text_step(1, "h")
    assert "error" in server.stepik_create_choice_step(1, "q", '["a"]', "[0]")
    assert "error" in server.stepik_create_code_step(1, "t")
    assert "error" in server.stepik_create_video_step(1, 2)
    assert "error" in server.stepik_create_string_step(1, "t", "p")
    assert "error" in server.stepik_create_number_step(1, "t", 1.0)
    assert "error" in server.stepik_create_matching_step(1, "t", "[]")
    assert "error" in server.stepik_create_sorting_step(1, "t", "[]")
    assert "error" in server.stepik_create_free_answer_step(1, "t")
    assert "error" in server.stepik_create_review_step(1, "t")
    assert server.stepik_update_course(1)["error"] == "nothing_to_update"
