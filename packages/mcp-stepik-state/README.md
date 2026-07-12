# mcp-stepik-state

PyPI: **`mcp-stepik-state`** · import: `mcp_state`

Persistent sessions and workspaces (Rust / PyO3 + embedded SQLite).

```bash
uv sync
(cd packages/mcp-stepik-state && maturin develop)
```

```python
from mcp_state import StateStore

store = StateStore("state/sessions.db")
sid = store.create_session(meta='{"client":"demo"}')
wid = store.create_workspace(project_id="p1", path="workspaces/ws1", ref_name="main")
store.set_active_workspace(sid, wid)
```
