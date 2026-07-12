"""Env settings for MCP Stepik server."""

from __future__ import annotations

import os

STEPIK_API_HOST = os.environ.get("STEPIK_API_HOST", "https://stepik.org").rstrip("/")
STEPIK_CLIENT_ID = os.environ.get("STEPIK_CLIENT_ID", "")
STEPIK_CLIENT_SECRET = os.environ.get("STEPIK_CLIENT_SECRET", "")

MCP_HOST = os.environ.get("MCP_STEPIK_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("MCP_STEPIK_PORT", "8000"))

SYNC_TARGETS = ("sync", "publish", "upload_video")
VIDEO_POLL_INTERVAL_SEC = float(os.environ.get("MCP_STEPIK_VIDEO_POLL", "2"))
VIDEO_POLL_TIMEOUT_SEC = float(os.environ.get("MCP_STEPIK_VIDEO_TIMEOUT", "600"))
TASK_WAIT_TIMEOUT_SEC = float(os.environ.get("MCP_STEPIK_TASK_WAIT", "600"))
