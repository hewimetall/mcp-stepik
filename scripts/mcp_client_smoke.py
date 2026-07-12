#!/usr/bin/env python3
"""Run use-cases against mcp-stepik as a real MCP HTTP client.

Starts nothing itself — expects server already listening, OR pass --spawn.

Examples:
  # terminal 1
  uv run mcp-stepik
  # terminal 2
  python scripts/mcp_client_smoke.py --url http://127.0.0.1:8000/mcp

  python scripts/mcp_client_smoke.py --spawn --port 8765
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastmcp.client import Client

ROOT = Path(__file__).resolve().parents[1]


async def call(client: Client[Any], name: str, args: dict[str, Any] | None = None) -> Any:
    result = await client.call_tool(name, args or {})
    # FastMCP returns CallToolResult; prefer structured/data
    if hasattr(result, "data") and result.data is not None:
        return result.data
    if hasattr(result, "structured_content") and result.structured_content is not None:
        return result.structured_content
    if hasattr(result, "content"):
        texts = []
        for c in result.content or []:
            t = getattr(c, "text", None)
            if t:
                texts.append(t)
        if len(texts) == 1:
            try:
                return json.loads(texts[0])
            except json.JSONDecodeError:
                return texts[0]
        return texts
    return result


def _print(status: str, uc: str, detail: str) -> None:
    print(f"{status:4}  {uc}: {detail}")


async def uc_workflow(client: Client[Any]) -> list[tuple[str, str, str]]:
    """UC1: presentation-like IR workflow."""
    out: list[tuple[str, str, str]] = []
    try:
        session = await call(client, "create_session", {"meta": '{"uc":"workflow"}'})
        sid = session["session_id"]
        await call(client, "create_project", {"project_id": "smoke1", "title": "Smoke"})
        ws = await call(
            client,
            "checkout_workspace",
            {"session_id": sid, "project_id": "smoke1", "workspace_id": "ws-smoke1"},
        )
        ir = {
            "course": {
                "title": "MCP Client Smoke",
                "summary": "via MCP client",
                "description": "<p>uc workflow</p>",
                "language": "ru",
            },
            "sections": [
                {
                    "title": "Mod 1",
                    "lessons": [
                        {
                            "title": "Lesson 1",
                            "steps": [
                                {"type": "text", "html": "<p>hello via MCP</p>"},
                                {
                                    "type": "choice",
                                    "question": "1+1?",
                                    "options": [
                                        {"text": "1", "is_correct": False},
                                        {"text": "2", "is_correct": True},
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
        }
        saved = await call(client, "save_course_ir", {"session_id": sid, "ir_json": json.dumps(ir)})
        synced = await call(client, "sync_course", {"session_id": sid})
        url = await call(client, "get_course_page_url", {"session_id": sid})
        # publish may fail for account plan — record either way
        published = await call(client, "publish_course", {"session_id": sid})
        course_id = url.get("course_id") or synced.get("artifact")
        deleted = None
        if course_id:
            deleted = await call(client, "stepik_delete_course", {"course_id": int(course_id)})
        out.append(
            (
                "PASS",
                "UC1_workflow",
                f"session={sid} ws={ws.get('workspace_id')} saved={saved.get('path')} "
                f"sync={synced.get('status')} url={url.get('url')} "
                f"publish={published.get('status') or published.get('error')} "
                f"delete={deleted}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        out.append(("FAIL", "UC1_workflow", str(exc)))
    return out


async def uc_crud(client: Client[Any]) -> list[tuple[str, str, str]]:
    """UC2: fine-grained Stepik CRUD tools via MCP."""
    out: list[tuple[str, str, str]] = []
    course_id = None
    try:
        h = await call(client, "stepik_health_check")
        if not h.get("ok"):
            out.append(("FAIL", "UC2_health", str(h)))
            return out
        created = await call(client, "stepik_create_course", {"title": "MCP CRUD smoke", "summary": "uc2"})
        course_id = created["id"]
        await call(client, "stepik_update_course", {"course_id": course_id, "summary": "updated"})
        sec = await call(
            client, "stepik_create_section", {"course_id": course_id, "title": "S", "position": 1}
        )
        await call(client, "stepik_update_section", {"section_id": sec["id"], "title": "S2"})
        sections = await call(client, "stepik_get_sections", {"course_id": course_id})
        les = await call(client, "stepik_create_lesson", {"title": "L"})
        await call(client, "stepik_update_lesson", {"lesson_id": les["id"], "title": "L2"})
        unit = await call(
            client,
            "stepik_create_unit",
            {"section_id": sec["id"], "lesson_id": les["id"], "position": 1},
        )
        text = await call(
            client,
            "stepik_create_text_step",
            {"lesson_id": les["id"], "text_html": "<p>t</p>", "position": 1},
        )
        choice = await call(
            client,
            "stepik_create_choice_step",
            {
                "lesson_id": les["id"],
                "question": "q",
                "choices_json": '["a","b"]',
                "correct_indices_json": "[1]",
                "position": 2,
            },
        )
        code = await call(
            client,
            "stepik_create_code_step",
            {"lesson_id": les["id"], "text": "<p>c</p>", "position": 3},
        )
        string = await call(
            client,
            "stepik_create_string_step",
            {"lesson_id": les["id"], "text": "s", "pattern": "hi", "position": 4},
        )
        number = await call(
            client,
            "stepik_create_number_step",
            {"lesson_id": les["id"], "text": "n", "answer": 42.0, "position": 5},
        )
        matching = await call(
            client,
            "stepik_create_matching_step",
            {
                "lesson_id": les["id"],
                "text": "m",
                "pairs_json": '[{"first":"a","second":"1"}]',
                "position": 6,
            },
        )
        sorting = await call(
            client,
            "stepik_create_sorting_step",
            {"lesson_id": les["id"], "text": "sort", "items_json": '["1","2"]', "position": 7},
        )
        free = await call(
            client,
            "stepik_create_free_answer_step",
            {"lesson_id": les["id"], "text": "essay", "position": 8},
        )
        review = await call(
            client,
            "stepik_create_review_step",
            {"lesson_id": les["id"], "text": "peer", "position": 9},
        )
        steps = await call(client, "stepik_get_steps", {"lesson_id": les["id"]})
        listed = await call(client, "stepik_list_courses", {"page": 1})
        got = await call(client, "stepik_get_course", {"course_id": course_id})
        # cleanup bottom-up-ish
        await call(client, "stepik_delete_course", {"course_id": course_id})
        course_id = None
        out.append(
            (
                "PASS",
                "UC2_crud",
                f"course={got.get('id')} sections={len(sections.get('sections') or [])} "
                f"unit={unit.get('id')} steps={len(steps.get('steps') or [])} "
                f"created={[x.get('id') for x in [text,choice,code,string,number,matching,sorting,free] if isinstance(x, dict)]} "
                f"review={review} listed={len(listed.get('courses') or [])}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        out.append(("FAIL", "UC2_crud", str(exc)))
        if course_id:
            try:
                await call(client, "stepik_delete_course", {"course_id": int(course_id)})
            except Exception:  # noqa: BLE001
                pass
    return out


async def uc_session_tools(client: Client[Any]) -> list[tuple[str, str, str]]:
    """UC3: session/workspace tools only."""
    out: list[tuple[str, str, str]] = []
    try:
        s = await call(client, "create_session")
        sid = s["session_id"]
        await call(client, "create_project", {"project_id": "p2"})
        await call(client, "checkout_workspace", {"session_id": sid, "project_id": "p2", "workspace_id": "ws2"})
        sessions = await call(client, "list_sessions")
        ws = await call(client, "get_workspace", {"workspace_id": "ws2"})
        listed = await call(client, "list_workspaces", {"project_id": "p2"})
        await call(client, "set_active_workspace", {"session_id": sid, "workspace_id": "ws2"})
        await call(client, "remove_workspace", {"workspace_id": "ws2"})
        out.append(
            (
                "PASS",
                "UC3_sessions",
                f"sessions={len(sessions.get('sessions') or [])} ws_status_before_remove={ws.get('status')} "
                f"listed={len(listed.get('workspaces') or [])}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        out.append(("FAIL", "UC3_sessions", str(exc)))
    return out


async def run_ucs(url: str) -> int:
    print(f"MCP client → {url}")
    async with Client(url, timeout=120) as client:
        tools = await client.list_tools()
        print(f"tools available: {len(tools)}")
        results: list[tuple[str, str, str]] = []
        results += await uc_session_tools(client)
        results += await uc_workflow(client)
        results += await uc_crud(client)

    print("\n=== MCP CLIENT UC SUMMARY ===")
    counts = {"PASS": 0, "FAIL": 0}
    for status, name, detail in results:
        _print(status, name, detail[:400])
        counts[status] = counts.get(status, 0) + 1
    print(counts)
    return 1 if counts.get("FAIL") else 0


def spawn_server(port: int) -> subprocess.Popen[Any]:
    env = os.environ.copy()
    env["MCP_STEPIK_HOST"] = "127.0.0.1"
    env["MCP_STEPIK_PORT"] = str(port)
    env.setdefault("MCP_STEPIK_STATE", "/tmp/mcp-stepik-smoke/state")
    env.setdefault("MCP_STEPIK_PROJECTS", "/tmp/mcp-stepik-smoke/projects")
    env.setdefault("MCP_STEPIK_WORKSPACES", "/tmp/mcp-stepik-smoke/workspaces")
    env["PYTHONPATH"] = (
        f"{ROOT / 'python'}:{ROOT / 'packages' / 'mcp-stepik-state' / 'python'}:"
        + env.get("PYTHONPATH", "")
    )
    Path(env["MCP_STEPIK_STATE"]).mkdir(parents=True, exist_ok=True)
    Path(env["MCP_STEPIK_PROJECTS"]).mkdir(parents=True, exist_ok=True)
    Path(env["MCP_STEPIK_WORKSPACES"]).mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        [sys.executable, "-m", "mcp_stepik.server"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def wait_http(url: str, timeout: float = 30.0) -> None:
    import urllib.error
    import urllib.request

    # FastMCP MCP endpoint may 406 on plain GET; any TCP response means up.
    base = url.rstrip("/").rsplit("/mcp", 1)[0] or url
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base + "/", timeout=1)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            # connection refused vs other
            if "Connection refused" not in str(exc):
                return
            time.sleep(0.3)
    raise RuntimeError(f"server not up: {last}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.environ.get("MCP_STEPIK_URL", "http://127.0.0.1:8000/mcp"))
    parser.add_argument("--spawn", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    proc = None
    url = args.url
    try:
        if args.spawn:
            url = f"http://127.0.0.1:{args.port}/mcp"
            proc = spawn_server(args.port)
            wait_http(url)
            time.sleep(0.5)
        return asyncio.run(run_ucs(url))
    finally:
        if proc is not None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
