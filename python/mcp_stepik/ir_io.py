"""Write / read course.ir.json in a workspace."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp_stepik.ir_models import CourseIR, validate_ir_obj
from mcp_stepik.paths import IR_FILENAME


def write_ir(workspace: Path, ir: CourseIR | dict[str, Any] | str) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    if isinstance(ir, str):
        parsed = validate_ir_obj(ir)
    elif isinstance(ir, CourseIR):
        parsed = ir
    else:
        parsed = validate_ir_obj(ir)
    path = workspace / IR_FILENAME
    path.write_text(
        json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def read_ir(workspace: Path) -> CourseIR:
    path = workspace / IR_FILENAME
    if not path.exists():
        raise FileNotFoundError(f"missing {IR_FILENAME} in {workspace}")
    return validate_ir_obj(json.loads(path.read_text(encoding="utf-8")))
