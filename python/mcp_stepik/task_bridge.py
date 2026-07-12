"""Poll SQLite TaskStore until done/error (presentation-style wait)."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol


class _TaskStore(Protocol):
    def get(self, task_id: str) -> Any: ...


async def await_sqlite_task(
    store: _TaskStore,
    task_id: str,
    *,
    poll_interval: float = 0.5,
    timeout: float = 600.0,
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        row = await asyncio.to_thread(store.get, task_id)
        if row is None:
            raise TimeoutError(f"task disappeared: {task_id}")
        status = row.get("status")
        if status in {"done", "error"}:
            return dict(row)
        if loop.time() >= deadline:
            raise TimeoutError(f"wait_timeout task_id={task_id} last_status={status}")
        await asyncio.sleep(poll_interval)
