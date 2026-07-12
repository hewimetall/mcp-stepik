"""sync_course_ir with fake client."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_stepik.ir_io import write_ir
from mcp_stepik.ir_models import validate_ir_obj
from mcp_stepik.sync import sync_course_ir, wait_video_ready


class Fake:
    def __init__(self) -> None:
        self.sections: list[dict[str, Any]] = []
        self.units: list[dict[str, Any]] = []
        self.steps: list[dict[str, Any]] = []

    def create_course(self, title: str, **fields: Any) -> dict[str, Any]:
        return {"id": 5, "title": title}

    def update_course(self, course_id: int, **fields: Any) -> dict[str, Any]:
        return {"id": course_id}

    def list_sections(self, course_id: int) -> list[dict[str, Any]]:
        return list(self.sections)

    def create_section(self, course_id: int, title: str, position: int = 1) -> dict[str, Any]:
        row = {"id": 10 + position, "title": title, "course": course_id}
        self.sections.append(row)
        return row

    def update_section(self, section_id: int, **fields: Any) -> dict[str, Any]:
        return {"id": section_id, **fields}

    def list_units(self, section_id: int) -> list[dict[str, Any]]:
        return [u for u in self.units if u["section"] == section_id]

    def create_lesson(self, title: str, is_public: bool = False) -> dict[str, Any]:
        return {"id": 20, "title": title}

    def update_lesson(self, lesson_id: int, **fields: Any) -> dict[str, Any]:
        return {"id": lesson_id}

    def create_unit(self, section_id: int, lesson_id: int, position: int = 1) -> dict[str, Any]:
        row = {"id": 30, "section": section_id, "lesson": lesson_id, "position": position}
        self.units.append(row)
        return row

    def list_steps(self, lesson_id: int) -> list[dict[str, Any]]:
        return list(self.steps)

    def create_step_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {"id": 40 + len(self.steps)}
        self.steps.append({"id": row["id"], "position": payload["position"]})
        return row

    def update_step_source(self, step_source_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return {"id": step_source_id}

    def get_video(self, video_id: int) -> dict[str, Any]:
        return {"id": video_id, "status": "ready"}


def test_sync_creates(tmp_path: Path) -> None:
    ir = validate_ir_obj(
        {
            "course": {"title": "T", "summary": "s"},
            "sections": [
                {
                    "title": "S",
                    "lessons": [
                        {
                            "title": "L",
                            "steps": [
                                {"type": "text", "html": "<p>x</p>"},
                                {
                                    "type": "choice",
                                    "question": "q",
                                    "options": [{"text": "a", "is_correct": True}],
                                },
                            ],
                        }
                    ],
                }
            ],
        }
    )
    write_ir(tmp_path, ir)
    result = sync_course_ir(Fake(), tmp_path)  # type: ignore[arg-type]
    assert result["course_id"] == 5
    # second sync updates
    result2 = sync_course_ir(Fake(), tmp_path)  # type: ignore[arg-type]
    assert result2["course_id"] == 5


def test_wait_video_ready() -> None:
    v = wait_video_ready(Fake(), 1)  # type: ignore[arg-type]
    assert v["status"] == "ready"
