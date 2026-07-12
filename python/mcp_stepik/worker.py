"""Background worker: claim TaskStore jobs and run sync / upload_video / publish."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from mcp_stepik.client import StepikClient, StepikError, get_client
from mcp_stepik.sync import _load_meta, _save_meta, sync_course_ir, upload_video_file


class SyncWorker:
    def __init__(self, tasks: Any, client: StepikClient | None = None) -> None:
        self._tasks = tasks
        self._client = client
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def wake(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="stepik-worker", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        client = self._client or get_client()
        idle_rounds = 0
        while idle_rounds < 50 and not self._stop.is_set():
            row = self._tasks.claim_next()
            if row is None:
                idle_rounds += 1
                self._stop.wait(0.1)
                continue
            idle_rounds = 0
            tid = row["task_id"]
            target = row["target"]
            workspace = Path(row["workspace"] or ".")
            try:
                artifact, logs = self._run(client, target, workspace, row)
                self._tasks.update(tid, status="done", artifact=artifact, logs=logs, error="")
            except Exception as exc:  # noqa: BLE001 — surface to task row
                self._tasks.update(tid, status="error", error=str(exc), logs="")

    def _run(
        self,
        client: StepikClient,
        target: str,
        workspace: Path,
        row: dict[str, Any],
    ) -> tuple[str, str]:
        if target == "sync":
            result = sync_course_ir(client, workspace)
            return str(result["course_id"]), result.get("logs", "")
        if target == "publish":
            meta = _load_meta(workspace)
            course_id = meta.get("course_id")
            if not course_id:
                raise StepikError("no course_id in workspace meta — sync first")
            course = client.publish_course(int(course_id))
            return str(course["id"]), f"published course {course['id']}"
        if target == "upload_video":
            # artifact field may hold JSON {"path": "...", "lesson_id": N}
            payload: dict[str, Any] = {}
            raw = row.get("artifact") or ""
            if raw.startswith("{"):
                payload = json.loads(raw)
            path = payload.get("path") or raw
            if not path:
                raise StepikError("upload_video requires artifact path JSON or string")
            lesson_id = payload.get("lesson_id")
            video = upload_video_file(
                client,
                workspace,
                str(path),
                lesson_id=int(lesson_id) if lesson_id is not None else None,
            )
            meta = _load_meta(workspace)
            videos = meta.setdefault("videos", {})
            videos[str(path)] = video["id"]
            _save_meta(workspace, meta)
            return str(video["id"]), f"video_id={video['id']} status={video.get('status')}"
        raise StepikError(f"unknown target: {target}")


_worker: SyncWorker | None = None


def wake_worker(tasks: Any) -> SyncWorker:
    global _worker
    if _worker is None:
        _worker = SyncWorker(tasks)
    _worker.wake()
    return _worker
