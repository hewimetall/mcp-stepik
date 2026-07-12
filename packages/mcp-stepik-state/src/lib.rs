use parking_lot::Mutex;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use rusqlite::{params, Connection, OptionalExtension};
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};
use uuid::Uuid;

const SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS sessions (
    session_id          TEXT PRIMARY KEY,
    active_workspace_id TEXT,
    meta                TEXT,
    created_at          INTEGER NOT NULL,
    updated_at          INTEGER NOT NULL,
    FOREIGN KEY (active_workspace_id) REFERENCES workspaces(workspace_id)
);

CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL,
    path         TEXT NOT NULL UNIQUE,
    ref_name     TEXT,
    status       TEXT NOT NULL DEFAULT 'active',
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workspaces_project
  ON workspaces(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_active_ws
  ON sessions(active_workspace_id);
"#;

fn now_secs() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

fn open_db(path: &str) -> PyResult<Connection> {
    if let Some(parent) = Path::new(path).parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent).map_err(|e| {
                PyValueError::new_err(format!("cannot create db dir {}: {e}", parent.display()))
            })?;
        }
    }
    let conn = Connection::open(path)
        .map_err(|e| PyValueError::new_err(format!("sqlite open {path}: {e}")))?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL;
         PRAGMA busy_timeout=30000;
         PRAGMA foreign_keys=ON;",
    )
    .map_err(|e| PyValueError::new_err(format!("pragma: {e}")))?;
    // workspaces first (FK from sessions)
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS workspaces (
            workspace_id TEXT PRIMARY KEY,
            project_id   TEXT NOT NULL,
            path         TEXT NOT NULL UNIQUE,
            ref_name     TEXT,
            status       TEXT NOT NULL DEFAULT 'active',
            created_at   INTEGER NOT NULL,
            updated_at   INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id          TEXT PRIMARY KEY,
            active_workspace_id TEXT,
            meta                TEXT,
            created_at          INTEGER NOT NULL,
            updated_at          INTEGER NOT NULL,
            FOREIGN KEY (active_workspace_id) REFERENCES workspaces(workspace_id)
        );
        CREATE INDEX IF NOT EXISTS idx_workspaces_project
          ON workspaces(project_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_active_ws
          ON sessions(active_workspace_id);",
    )
    .map_err(|e| PyValueError::new_err(format!("schema: {e}")))?;
    let _ = SCHEMA; // documented schema constant
    Ok(conn)
}

/// Persistent sessions + workspaces store (embedded SQLite via rusqlite).
/// Separate package from mcp-presentation TaskStore.
#[pyclass(name = "StateStore")]
struct StateStore {
    conn: Mutex<Connection>,
}

#[pymethods]
impl StateStore {
    #[new]
    fn new(path: &str) -> PyResult<Self> {
        Ok(Self {
            conn: Mutex::new(open_db(path)?),
        })
    }

    /// Create a session; returns session_id.
    #[pyo3(signature = (meta=None))]
    fn create_session(&self, meta: Option<&str>) -> PyResult<String> {
        let sid = Uuid::new_v4().to_string();
        let ts = now_secs();
        let conn = self.conn.lock();
        conn.execute(
            "INSERT INTO sessions(session_id, active_workspace_id, meta, created_at, updated_at)
             VALUES (?1, NULL, ?2, ?3, ?3)",
            params![sid, meta, ts],
        )
        .map_err(|e| PyValueError::new_err(format!("create_session: {e}")))?;
        Ok(sid)
    }

    fn get_session<'py>(
        &self,
        py: Python<'py>,
        session_id: &str,
    ) -> PyResult<Option<Bound<'py, PyDict>>> {
        let conn = self.conn.lock();
        let row = conn
            .query_row(
                "SELECT session_id, active_workspace_id, meta, created_at, updated_at
                 FROM sessions WHERE session_id = ?1",
                params![session_id],
                |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, Option<String>>(1)?,
                        r.get::<_, Option<String>>(2)?,
                        r.get::<_, i64>(3)?,
                        r.get::<_, i64>(4)?,
                    ))
                },
            )
            .optional()
            .map_err(|e| PyValueError::new_err(format!("get_session: {e}")))?;
        row.map(|t| session_to_dict(py, t)).transpose()
    }

    fn list_sessions<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let conn = self.conn.lock();
        let mut stmt = conn
            .prepare(
                "SELECT session_id, active_workspace_id, meta, created_at, updated_at
                 FROM sessions ORDER BY created_at ASC",
            )
            .map_err(|e| PyValueError::new_err(format!("list_sessions: {e}")))?;
        let rows = stmt
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, Option<String>>(1)?,
                    r.get::<_, Option<String>>(2)?,
                    r.get::<_, i64>(3)?,
                    r.get::<_, i64>(4)?,
                ))
            })
            .map_err(|e| PyValueError::new_err(format!("list_sessions query: {e}")))?;

        let list = PyList::empty(py);
        for row in rows {
            let t = row.map_err(|e| PyValueError::new_err(format!("list_sessions row: {e}")))?;
            list.append(session_to_dict(py, t)?)?;
        }
        Ok(list)
    }

    /// Register a workspace checkout (metadata only; git worktree is separate).
    /// If `workspace_id` is provided, it is stored as-is (must match the on-disk dir name).
    #[pyo3(signature = (project_id, path, ref_name=None, workspace_id=None))]
    fn create_workspace(
        &self,
        project_id: &str,
        path: &str,
        ref_name: Option<&str>,
        workspace_id: Option<&str>,
    ) -> PyResult<String> {
        let wid = match workspace_id {
            Some(id) if !id.is_empty() => id.to_string(),
            _ => Uuid::new_v4().to_string(),
        };
        let ts = now_secs();
        let conn = self.conn.lock();
        conn.execute(
            "INSERT INTO workspaces(
                workspace_id, project_id, path, ref_name, status, created_at, updated_at
             ) VALUES (?1, ?2, ?3, ?4, 'active', ?5, ?5)",
            params![wid, project_id, path, ref_name, ts],
        )
        .map_err(|e| PyValueError::new_err(format!("create_workspace: {e}")))?;
        Ok(wid)
    }

    fn get_workspace<'py>(
        &self,
        py: Python<'py>,
        workspace_id: &str,
    ) -> PyResult<Option<Bound<'py, PyDict>>> {
        let conn = self.conn.lock();
        let row = conn
            .query_row(
                "SELECT workspace_id, project_id, path, ref_name, status, created_at, updated_at
                 FROM workspaces WHERE workspace_id = ?1",
                params![workspace_id],
                |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, String>(1)?,
                        r.get::<_, String>(2)?,
                        r.get::<_, Option<String>>(3)?,
                        r.get::<_, String>(4)?,
                        r.get::<_, i64>(5)?,
                        r.get::<_, i64>(6)?,
                    ))
                },
            )
            .optional()
            .map_err(|e| PyValueError::new_err(format!("get_workspace: {e}")))?;
        row.map(|t| workspace_to_dict(py, t)).transpose()
    }

    #[pyo3(signature = (project_id=None, status=None))]
    fn list_workspaces<'py>(
        &self,
        py: Python<'py>,
        project_id: Option<&str>,
        status: Option<&str>,
    ) -> PyResult<Bound<'py, PyList>> {
        let conn = self.conn.lock();
        let mut sql = String::from(
            "SELECT workspace_id, project_id, path, ref_name, status, created_at, updated_at
             FROM workspaces WHERE 1=1",
        );
        let mut binds: Vec<String> = Vec::new();
        if let Some(p) = project_id {
            sql.push_str(" AND project_id = ?");
            binds.push(p.to_string());
        }
        if let Some(s) = status {
            sql.push_str(" AND status = ?");
            binds.push(s.to_string());
        }
        sql.push_str(" ORDER BY created_at ASC");

        let mut stmt = conn
            .prepare(&sql)
            .map_err(|e| PyValueError::new_err(format!("list_workspaces: {e}")))?;

        let param_refs: Vec<&dyn rusqlite::types::ToSql> = binds
            .iter()
            .map(|b| b as &dyn rusqlite::types::ToSql)
            .collect();

        let rows = stmt
            .query_map(param_refs.as_slice(), |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, Option<String>>(3)?,
                    r.get::<_, String>(4)?,
                    r.get::<_, i64>(5)?,
                    r.get::<_, i64>(6)?,
                ))
            })
            .map_err(|e| PyValueError::new_err(format!("list_workspaces query: {e}")))?;

        let list = PyList::empty(py);
        for row in rows {
            let t = row.map_err(|e| PyValueError::new_err(format!("list_workspaces row: {e}")))?;
            list.append(workspace_to_dict(py, t)?)?;
        }
        Ok(list)
    }

    /// Point session at an existing workspace (active checkout).
    fn set_active_workspace(&self, session_id: &str, workspace_id: &str) -> PyResult<()> {
        let ts = now_secs();
        let conn = self.conn.lock();
        let exists: bool = conn
            .query_row(
                "SELECT 1 FROM workspaces WHERE workspace_id = ?1 AND status = 'active'",
                params![workspace_id],
                |_| Ok(true),
            )
            .optional()
            .map_err(|e| PyValueError::new_err(format!("set_active_workspace ws: {e}")))?
            .unwrap_or(false);
        if !exists {
            return Err(PyValueError::new_err(format!(
                "active workspace not found: {workspace_id}"
            )));
        }
        let n = conn
            .execute(
                "UPDATE sessions SET active_workspace_id = ?2, updated_at = ?3
                 WHERE session_id = ?1",
                params![session_id, workspace_id, ts],
            )
            .map_err(|e| PyValueError::new_err(format!("set_active_workspace: {e}")))?;
        if n == 0 {
            return Err(PyValueError::new_err(format!(
                "session not found: {session_id}"
            )));
        }
        Ok(())
    }

    /// Mark workspace removed (does not delete git worktree on disk).
    fn mark_workspace_removed(&self, workspace_id: &str) -> PyResult<()> {
        let ts = now_secs();
        let conn = self.conn.lock();
        let n = conn
            .execute(
                "UPDATE workspaces SET status = 'removed', updated_at = ?2
                 WHERE workspace_id = ?1",
                params![workspace_id, ts],
            )
            .map_err(|e| PyValueError::new_err(format!("mark_workspace_removed: {e}")))?;
        if n == 0 {
            return Err(PyValueError::new_err(format!(
                "workspace not found: {workspace_id}"
            )));
        }
        // clear active pointers
        conn.execute(
            "UPDATE sessions SET active_workspace_id = NULL, updated_at = ?2
             WHERE active_workspace_id = ?1",
            params![workspace_id, ts],
        )
        .map_err(|e| PyValueError::new_err(format!("clear active: {e}")))?;
        Ok(())
    }
}

type SessionRow = (String, Option<String>, Option<String>, i64, i64);
type WorkspaceRow = (String, String, String, Option<String>, String, i64, i64);

fn session_to_dict(py: Python<'_>, t: SessionRow) -> PyResult<Bound<'_, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("session_id", t.0)?;
    d.set_item("active_workspace_id", t.1)?;
    d.set_item("meta", t.2)?;
    d.set_item("created_at", t.3)?;
    d.set_item("updated_at", t.4)?;
    Ok(d)
}

fn workspace_to_dict(py: Python<'_>, t: WorkspaceRow) -> PyResult<Bound<'_, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("workspace_id", t.0)?;
    d.set_item("project_id", t.1)?;
    d.set_item("path", t.2)?;
    d.set_item("ref_name", t.3)?;
    d.set_item("status", t.4)?;
    d.set_item("created_at", t.5)?;
    d.set_item("updated_at", t.6)?;
    Ok(d)
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<StateStore>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::types::PyAnyMethods;
    use tempfile::tempdir;

    #[test]
    fn module_registers_state_store() {
        Python::attach(|py| {
            let m = PyModule::new(py, "s").unwrap();
            _native(&m).unwrap();
            assert!(m.getattr("StateStore").is_ok());
        });
    }

    #[test]
    fn session_workspace_lifecycle() {
        let dir = tempdir().unwrap();
        let db = dir.path().join("nested").join("sessions.db");
        Python::attach(|py| {
            let store = StateStore::new(db.to_str().unwrap()).unwrap();
            let sid = store.create_session(Some(r#"{"c":1}"#)).unwrap();
            assert!(store.get_session(py, "nope").unwrap().is_none());
            let session = store.get_session(py, &sid).unwrap().unwrap();
            assert!(session
                .get_item("active_workspace_id")
                .unwrap()
                .unwrap()
                .is_none());

            let sessions = store.list_sessions(py).unwrap();
            assert_eq!(sessions.len(), 1);

            let wid = store
                .create_workspace("p1", "/ws1", Some("main"), None)
                .unwrap();
            let fixed = store
                .create_workspace("p1", "/named", Some("main"), Some("named-ws"))
                .unwrap();
            assert_eq!(fixed, "named-ws");

            store.set_active_workspace(&sid, &wid).unwrap();
            let session = store.get_session(py, &sid).unwrap().unwrap();
            assert_eq!(
                session
                    .get_item("active_workspace_id")
                    .unwrap()
                    .unwrap()
                    .extract::<String>()
                    .unwrap(),
                wid
            );

            let listed = store
                .list_workspaces(py, Some("p1"), Some("active"))
                .unwrap();
            assert_eq!(listed.len(), 2);
            let all = store.list_workspaces(py, None, None).unwrap();
            assert_eq!(all.len(), 2);

            store.mark_workspace_removed(&wid).unwrap();
            let ws = store.get_workspace(py, &wid).unwrap().unwrap();
            assert_eq!(
                ws.get_item("status")
                    .unwrap()
                    .unwrap()
                    .extract::<String>()
                    .unwrap(),
                "removed"
            );
            let session = store.get_session(py, &sid).unwrap().unwrap();
            assert!(session
                .get_item("active_workspace_id")
                .unwrap()
                .unwrap()
                .is_none());
        });
    }

    #[test]
    fn set_active_errors() {
        let dir = tempdir().unwrap();
        let store = StateStore::new(dir.path().join("s.db").to_str().unwrap()).unwrap();
        let sid = store.create_session(None).unwrap();
        assert!(store.set_active_workspace(&sid, "ghost").is_err());
        let wid = store.create_workspace("p", "/p", None, Some("w1")).unwrap();
        assert!(store.set_active_workspace("missing-session", &wid).is_err());
        assert!(store.mark_workspace_removed("ghost").is_err());
    }

    #[test]
    fn open_db_fails_when_parent_is_file() {
        let dir = tempdir().unwrap();
        let blocker = dir.path().join("not-a-dir");
        std::fs::write(&blocker, b"x").unwrap();
        let db = blocker.join("sessions.db");
        assert!(StateStore::new(db.to_str().unwrap()).is_err());
    }

    #[test]
    fn now_secs_ok() {
        assert!(now_secs() >= 0);
    }
}
