#!/usr/bin/env python3
"""Live smoke against Stepik API — workflow + CRUD, then cleanup.

Requires STEPIK_CLIENT_ID / STEPIK_CLIENT_SECRET.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "python"), str(ROOT / "packages" / "mcp-stepik-state" / "python")]

from mcp_stepik.client import StepikClient, StepikError  # noqa: E402
from mcp_stepik.ir_io import write_ir  # noqa: E402
from mcp_stepik.ir_models import validate_ir_obj  # noqa: E402
from mcp_stepik.sync import sync_course_ir  # noqa: E402

Result = tuple[str, str, str]


def run() -> int:
    if not os.environ.get("STEPIK_CLIENT_ID") or not os.environ.get("STEPIK_CLIENT_SECRET"):
        print("Set STEPIK_CLIENT_ID and STEPIK_CLIENT_SECRET")
        return 2

    client = StepikClient(timeout=90)
    results: list[Result] = []
    course_id: int | None = None
    section_id: int | None = None
    lesson_id: int | None = None
    unit_id: int | None = None
    step_ids: list[int] = []
    sync_course_id: int | None = None

    def check(name: str, fn: Callable[[], str]) -> None:
        try:
            detail = fn()
            results.append(("PASS", name, detail))
            print(f"PASS  {name}  {detail}")
        except Exception as exc:  # noqa: BLE001
            results.append(("FAIL", name, f"{exc}"))
            print(f"FAIL  {name}  {exc}")

    def skip(name: str, detail: str) -> None:
        results.append(("SKIP", name, detail))
        print(f"SKIP  {name}  {detail}")

    check("health", lambda: str(client.health()))
    check(
        "list_my_courses",
        lambda: f"n={len(client.list_my_courses().get('courses') or [])}",
    )

    def create_course() -> str:
        nonlocal course_id
        c = client.create_course("MCP live smoke", summary="created by live_smoke.py")
        course_id = int(c["id"])
        return f"id={course_id}"

    check("create_course", create_course)
    check("get_course", lambda: f"title={client.get_course(course_id)['title']!r}")  # type: ignore[index]
    check(
        "update_course",
        lambda: f"summary={client.update_course(course_id, summary='summary updated').get('summary')!r}",  # type: ignore[arg-type]
    )

    def create_section() -> str:
        nonlocal section_id
        s = client.create_section(course_id, "Smoke Module", position=1)  # type: ignore[arg-type]
        section_id = int(s["id"])
        return f"id={section_id}"

    check("create_section", create_section)
    check("list_sections", lambda: f"n={len(client.list_sections(course_id))}")  # type: ignore[arg-type]
    check(
        "update_section",
        lambda: f"title={client.update_section(section_id, title='Smoke Module 2')['title']!r}",  # type: ignore[arg-type]
    )

    def create_lesson() -> str:
        nonlocal lesson_id
        les = client.create_lesson("Smoke Lesson")
        lesson_id = int(les["id"])
        return f"id={lesson_id}"

    check("create_lesson", create_lesson)
    check(
        "update_lesson",
        lambda: f"title={client.update_lesson(lesson_id, title='Smoke Lesson 2')['title']!r}",  # type: ignore[arg-type]
    )
    check("get_lesson", lambda: f"id={client.get_lesson(lesson_id)['id']}")  # type: ignore[arg-type]

    def create_unit() -> str:
        nonlocal unit_id
        u = client.create_unit(section_id, lesson_id, position=1)  # type: ignore[arg-type]
        unit_id = int(u["id"])
        return f"id={unit_id}"

    check("create_unit", create_unit)
    check("list_units", lambda: f"n={len(client.list_units(section_id))}")  # type: ignore[arg-type]

    def add(pos: int, block: dict[str, Any]) -> str:
        s = client.create_step_source({"lesson": lesson_id, "position": pos, "block": block})
        sid = int(s["id"])
        step_ids.append(sid)
        return f"id={sid}"

    check(
        "create_text_step",
        lambda: add(1, {"name": "text", "text": "<p>hello smoke</p>"}),
    )
    check(
        "create_choice_step",
        lambda: add(
            2,
            {
                "name": "choice",
                "text": "2+2?",
                "source": {
                    "options": [
                        {"text": "3", "is_correct": False, "feedback": ""},
                        {"text": "4", "is_correct": True, "feedback": ""},
                    ],
                    "is_always_correct": False,
                    "is_html_enabled": True,
                    "preserve_order": False,
                    "is_multiple_choice": False,
                    "sample_size": 2,
                    "is_options_feedback": False,
                },
            },
        ),
    )
    check(
        "create_code_step",
        lambda: add(
            3,
            {
                "name": "code",
                "text": "<p>print hi</p>",
                "source": {
                    "execution_time_limit": 5,
                    "execution_memory_limit": 256,
                    "samples_count": 1,
                    "templates_data": "print()",
                    "code": "",
                    "manual_time_limits": [],
                    "manual_memory_limits": [],
                    "test_archive": [],
                    "test_cases": [],
                    "is_run_user_code_allowed": True,
                    "is_time_limit_scaled": False,
                    "is_memory_limit_scaled": False,
                },
            },
        ),
    )
    check(
        "create_string_step",
        lambda: add(
            4,
            {
                "name": "string",
                "text": "type hello",
                "source": {
                    "pattern": "hello",
                    "code": "",
                    "case_sensitive": False,
                    "use_re": False,
                    "match_substring": False,
                },
            },
        ),
    )
    check(
        "create_number_step",
        lambda: add(
            5,
            {
                "name": "number",
                "text": "answer 42",
                "source": {"options": [{"answer": "42", "max_error": "0"}]},
            },
        ),
    )
    check(
        "create_matching_step",
        lambda: add(
            6,
            {
                "name": "matching",
                "text": "match",
                "source": {
                    "pairs": [{"first": "a", "second": "1"}],
                    "preserve_firsts_order": True,
                    "is_html_enabled": True,
                },
            },
        ),
    )
    check(
        "create_sorting_step",
        lambda: add(
            7,
            {
                "name": "sorting",
                "text": "sort",
                "source": {"options": [{"text": "1"}, {"text": "2"}]},
            },
        ),
    )
    check(
        "create_free_answer_step",
        lambda: add(8, {"name": "free-answer", "text": "essay", "source": {}}),
    )

    # review plugin missing on platform for this account
    try:
        add(
            9,
            {
                "name": "review",
                "text": "peer",
                "source": {"instructions_to_reviewer": "be kind"},
            },
        )
        results.append(("PASS", "create_review_step", "created"))
        print("PASS  create_review_step  created")
    except StepikError as exc:
        skip("create_review_step", f"unsupported on platform: {exc}")

    # video without ready upload — skip (needs upload_video task)
    skip("create_video_step", "needs upload_video / ready video_id")

    check(
        "list_steps",
        lambda: f"n={len(client.list_steps(lesson_id))} types="  # type: ignore[arg-type]
        f"{[(s.get('block') or {}).get('name') for s in client.list_steps(lesson_id)]}",  # type: ignore[arg-type]
    )
    check(
        "update_step_source",
        lambda: f"id={client.update_step_source(step_ids[0], {'block': {'name': 'text', 'text': '<p>updated</p>'}})['id']}",
    )

    def ir_sync() -> str:
        nonlocal sync_course_id
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            ir = validate_ir_obj(
                {
                    "course": {
                        "title": "MCP IR smoke",
                        "summary": "from IR",
                        "description": "<p>ir</p>",
                        "language": "ru",
                    },
                    "sections": [
                        {
                            "title": "IR Mod",
                            "lessons": [
                                {
                                    "title": "IR Lesson",
                                    "steps": [
                                        {"type": "text", "html": "<p>from ir</p>"},
                                        {
                                            "type": "choice",
                                            "question": "1+1?",
                                            "options": [
                                                {"text": "1", "is_correct": False},
                                                {"text": "2", "is_correct": True},
                                            ],
                                        },
                                        {
                                            "type": "code",
                                            "text": "<p>hi</p>",
                                            "templates_data": "print()",
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                }
            )
            write_ir(ws, ir)
            out = sync_course_ir(client, ws)
            sync_course_id = int(out["course_id"])
            return json.dumps({"course_id": sync_course_id, "url": out["url"]})

    check("sync_course_ir", ir_sync)

    # publish draft without paid/video features
    check(
        "publish_course",
        lambda: f"is_enabled={client.publish_course(course_id).get('is_enabled')}",  # type: ignore[arg-type]
    )

    check("delete_step", lambda: (client.delete_step(step_ids[-1]), f"deleted {step_ids[-1]}")[1])
    check("delete_unit", lambda: (client.delete_unit(unit_id), f"deleted {unit_id}")[1])  # type: ignore[arg-type]
    check("delete_lesson", lambda: (client.delete_lesson(lesson_id), f"deleted {lesson_id}")[1])  # type: ignore[arg-type]
    check(
        "delete_section",
        lambda: (client.delete_section(section_id), f"deleted {section_id}")[1],  # type: ignore[arg-type]
    )
    check(
        "delete_course",
        lambda: (client.delete_course(course_id), f"deleted {course_id}")[1],  # type: ignore[arg-type]
    )

    if sync_course_id is not None:
        check(
            "delete_course(ir)",
            lambda: (client.delete_course(sync_course_id), f"deleted {sync_course_id}")[1],  # type: ignore[arg-type]
        )
    else:
        skip("delete_course(ir)", "no sync course")

    client.close()

    print("\n=== SUMMARY ===")
    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for status, name, detail in results:
        counts[status] = counts.get(status, 0) + 1
        if status == "FAIL":
            print(f"FAIL  {name}: {detail[:300]}")
    print(counts)
    return 1 if counts.get("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(run())
