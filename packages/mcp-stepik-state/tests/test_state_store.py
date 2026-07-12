"""Smoke tests for mcp-stepik-state StateStore."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("mcp_state._native")

from mcp_state import StateStore


def test_session_and_workspace(tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    store = StateStore(str(db))

    sid = store.create_session(meta='{"client":"test"}')
    session = store.get_session(sid)
    assert session is not None
    assert session["active_workspace_id"] is None

    wid = store.create_workspace("proj-1", str(tmp_path / "ws1"), ref_name="main")
    ws = store.get_workspace(wid)
    assert ws["project_id"] == "proj-1"
    assert ws["status"] == "active"

    fixed = store.create_workspace(
        "proj-1",
        str(tmp_path / "named"),
        ref_name="main",
        workspace_id="named-ws",
    )
    assert fixed == "named-ws"
    assert store.get_workspace("named-ws")["path"] == str(tmp_path / "named")

    store.set_active_workspace(sid, wid)
    session = store.get_session(sid)
    assert session["active_workspace_id"] == wid

    listed = store.list_workspaces(project_id="proj-1")
    assert len(listed) == 2

    store.mark_workspace_removed(wid)
    assert store.get_workspace(wid)["status"] == "removed"
    assert store.get_session(sid)["active_workspace_id"] is None
