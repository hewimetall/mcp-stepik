"""On-disk layout: projects/* and workspaces/*."""

from __future__ import annotations

import os
import re
from pathlib import Path

_SAFE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")

ROOT = Path(os.environ.get("MCP_STEPIK_ROOT", ".")).resolve()
PROJECTS_DIR = Path(os.environ.get("MCP_STEPIK_PROJECTS", str(ROOT / "projects")))
WORKSPACES_DIR = Path(os.environ.get("MCP_STEPIK_WORKSPACES", str(ROOT / "workspaces")))

IR_FILENAME = "course.ir.json"
META_FILENAME = "project.meta.json"


def require_safe_id(value: str, *, kind: str = "id") -> str:
    if not _SAFE.match(value):
        msg = f"invalid {kind}: {value!r} (use [A-Za-z0-9._-]{{1,64}})"
        raise ValueError(msg)
    return value


def project_path(project_id: str) -> Path:
    pid = require_safe_id(project_id, kind="project_id")
    return PROJECTS_DIR / pid


def workspace_path(workspace_id: str) -> Path:
    wid = require_safe_id(workspace_id, kind="workspace_id")
    return WORKSPACES_DIR / wid
