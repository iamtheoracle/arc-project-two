"""Private, persistent storage for Oracle Arc conversations, memories, and tool permissions."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
import uuid
from pathlib import Path
from typing import Any


class ArcStore:
    def __init__(self, path: str | Path | None = None):
        configured = path or os.environ.get("ORACLE_ARC_DB_PATH", "data/oracle_arc.sqlite3")
        self.path = Path(configured)
        self._memory_uri: str | None = None
        self._memory_keeper: sqlite3.Connection | None = None
        if str(self.path) == ":memory:":
            # Each request uses a fresh connection. Keep a shared in-memory database
            # alive so those connections see the same schema and records.
            self._memory_uri = f"file:oracle_arc_{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._memory_keeper = sqlite3.connect(
                self._memory_uri, uri=True, check_same_thread=False
            )
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._initialize()
        if self._memory_uri is None:
            try:
                self.path.chmod(0o600)
            except OSError:
                pass

    def _connect(self) -> sqlite3.Connection:
        target = self._memory_uri or str(self.path)
        conn = sqlite3.connect(
            target, timeout=10, uri=self._memory_uri is not None
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    @contextmanager
    def _session(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._session() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                    content TEXT NOT NULL,
                    event_id TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);
                CREATE TABLE IF NOT EXISTS user_profile (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    profile_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS user_boundaries (
                    id TEXT PRIMARY KEY,
                    boundary TEXT NOT NULL,
                    context TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE INDEX IF NOT EXISTS idx_user_boundaries_active ON user_boundaries(active, created_at);
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    task_id TEXT PRIMARY KEY,
                    source_agent TEXT NOT NULL,
                    target_agent TEXT NOT NULL,
                    required_capabilities_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
                    connector_id TEXT,
                    provider TEXT,
                    error_code TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE INDEX IF NOT EXISTS idx_agent_tasks_created ON agent_tasks(created_at DESC);
                CREATE TABLE IF NOT EXISTS agent_task_outbox (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','leased','published')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at INTEGER NOT NULL DEFAULT (unixepoch()),
                    lease_owner TEXT,
                    lease_expires_at INTEGER,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE INDEX IF NOT EXISTS idx_agent_outbox_pending
                    ON agent_task_outbox(status, available_at, created_at);
                CREATE TABLE IF NOT EXISTS tool_permissions (
                    name TEXT PRIMARY KEY,
                    approved INTEGER NOT NULL CHECK(approved IN (0,1)),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS tool_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS integration_approvals (
                    integration_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    manifest_digest TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
                    decision_by TEXT,
                    decision_reason TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    decided_at TEXT,
                    PRIMARY KEY(integration_id,version,manifest_digest)
                );
                CREATE TABLE IF NOT EXISTS integration_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    integration_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    manifest_digest TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS integration_activation_approvals (
                    integration_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    manifest_digest TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','revoked')),
                    decision_by TEXT,
                    decision_reason TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    decided_at TEXT,
                    PRIMARY KEY(integration_id,version,manifest_digest)
                );
            """)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
            if "event_id" not in columns:
                conn.execute("ALTER TABLE messages ADD COLUMN event_id TEXT")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_event_id ON messages(event_id) WHERE event_id IS NOT NULL")
            task_columns = {row["name"] for row in conn.execute("PRAGMA table_info(agent_tasks)").fetchall()}
            for name, definition in (
                ("payload_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("result_json", "TEXT"),
                ("attempts", "INTEGER NOT NULL DEFAULT 0"),
                ("worker_id", "TEXT"),
                ("lease_expires_at", "INTEGER"),
            ):
                if name not in task_columns:
                    conn.execute(f"ALTER TABLE agent_tasks ADD COLUMN {name} {definition}")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_tasks_claim ON agent_tasks(status, lease_expires_at, created_at)")
            outbox_columns = {row["name"] for row in conn.execute("PRAGMA table_info(agent_task_outbox)").fetchall()}
            if "dead_letter" not in outbox_columns:
                conn.execute("ALTER TABLE agent_task_outbox ADD COLUMN dead_letter INTEGER NOT NULL DEFAULT 0")

    def create_conversation(self, title: str = "", conversation_id: str | None = None) -> str:
        conversation_id = conversation_id or str(uuid.uuid4())
        with self._session() as conn:
            conn.execute("INSERT INTO conversations(id,title) VALUES(?,?)", (conversation_id, title[:160]))
        return conversation_id

    def conversation_exists(self, conversation_id: str) -> bool:
        with self._session() as conn:
            return conn.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone() is not None

    def add_message(self, conversation_id: str, role: str, content: str,
                    event_id: str | None = None) -> int:
        if role not in ("user", "assistant"):
            raise ValueError("Unsupported message role")
        with self._session() as conn:
            if event_id is None:
                cursor = conn.execute(
                    "INSERT INTO messages(conversation_id,role,content) VALUES(?,?,?)",
                    (conversation_id, role, content),
                )
            else:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO messages(conversation_id,role,content,event_id) VALUES(?,?,?,?)",
                    (conversation_id, role, content, event_id),
                )
            conn.execute(
                "UPDATE conversations SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (conversation_id,),
            )
            return int(cursor.lastrowid)

    def rollback_pending_turn(self, conversation_id: str, message_id: int) -> None:
        """Remove only the failed request's user message and any now-empty new chat."""
        with self._session() as conn:
            conn.execute(
                "DELETE FROM messages WHERE id=? AND conversation_id=? AND role='user'",
                (message_id, conversation_id),
            )
            conn.execute(
                "DELETE FROM conversations WHERE id=? "
                "AND NOT EXISTS (SELECT 1 FROM messages WHERE conversation_id=?)",
                (conversation_id, conversation_id),
            )

    def get_messages(self, conversation_id: str, limit: int = 80) -> list[dict[str, str]]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT role,content FROM (SELECT id,role,content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?) ORDER BY id",
                (conversation_id, max(1, min(limit, 200))),
            ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._session() as conn:
            result = conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
        return result.rowcount > 0

    def list_conversations(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT c.id,c.title,c.created_at,c.updated_at,(SELECT content FROM messages m WHERE m.conversation_id=c.id ORDER BY m.id DESC LIMIT 1) AS last_message FROM conversations c ORDER BY c.updated_at DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_memory(self, content: str, tags: list[str] | None = None) -> dict[str, Any]:
        memory_id = str(uuid.uuid4())
        clean_tags = list(dict.fromkeys(t.strip()[:40] for t in (tags or []) if isinstance(t, str) and t.strip()))[:20]
        with self._session() as conn:
            conn.execute("INSERT INTO memories(id,content,tags_json) VALUES(?,?,?)",
                         (memory_id, content.strip(), json.dumps(clean_tags)))
            row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return self._memory_dict(row)

    def update_memory(self, memory_id: str, content: str, tags: list[str] | None = None) -> dict[str, Any] | None:
        clean_tags = list(dict.fromkeys(t.strip()[:40] for t in (tags or []) if isinstance(t, str) and t.strip()))[:20]
        with self._session() as conn:
            result = conn.execute(
                "UPDATE memories SET content=?,tags_json=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (content.strip(), json.dumps(clean_tags), memory_id),
            )
            if result.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return self._memory_dict(row)

    def list_memories(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute("SELECT * FROM memories ORDER BY created_at DESC LIMIT ?",
                                 (max(1, min(limit, 500)),)).fetchall()
        return [self._memory_dict(row) for row in rows]

    def delete_memory(self, memory_id: str) -> bool:
        with self._session() as conn:
            result = conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        return result.rowcount > 0

    @staticmethod
    def _memory_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "content": row["content"], "tags": json.loads(row["tags_json"]),
                "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def get_user_profile(self) -> dict[str, Any]:
        with self._session() as conn:
            row = conn.execute("SELECT profile_json FROM user_profile WHERE id=1").fetchone()
        return json.loads(row["profile_json"]) if row else {}

    def save_user_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(profile, ensure_ascii=False)
        with self._session() as conn:
            conn.execute(
                "INSERT INTO user_profile(id,profile_json) VALUES(1,?) "
                "ON CONFLICT(id) DO UPDATE SET profile_json=excluded.profile_json,"
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                (payload,),
            )
            row = conn.execute(
                "SELECT profile_json,updated_at FROM user_profile WHERE id=1"
            ).fetchone()
        return {"profile": json.loads(row["profile_json"]), "updated_at": row["updated_at"]}

    def add_boundary(self, boundary: str, context: str = "") -> dict[str, Any]:
        boundary_id = str(uuid.uuid4())
        with self._session() as conn:
            conn.execute(
                "INSERT INTO user_boundaries(id,boundary,context) VALUES(?,?,?)",
                (boundary_id, boundary.strip(), context.strip()),
            )
            row = conn.execute(
                "SELECT id,boundary,context,active,created_at,updated_at "
                "FROM user_boundaries WHERE id=?", (boundary_id,)
            ).fetchone()
        return dict(row)

    def list_boundaries(self, active_only: bool = True) -> list[dict[str, Any]]:
        query = (
            "SELECT id,boundary,context,active,created_at,updated_at "
            "FROM user_boundaries"
        )
        if active_only:
            query += " WHERE active=1"
        query += " ORDER BY created_at ASC"
        with self._session() as conn:
            rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]

    def deactivate_boundary(self, boundary_id: str) -> bool:
        with self._session() as conn:
            result = conn.execute(
                "UPDATE user_boundaries SET active=0,"
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE id=? AND active=1",
                (boundary_id,),
            )
        return result.rowcount > 0

    @staticmethod
    def _insert_task_event(conn: sqlite3.Connection, task_id: str, event_type: str,
                           payload: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO agent_task_outbox(event_id,task_id,event_type,payload_json) VALUES(?,?,?,?)",
            (uuid.uuid4().hex, task_id, event_type, json.dumps(payload, separators=(",", ":"))),
        )

    def create_agent_task(self, task_id: str, source_agent: str, target_agent: str,
                          required_capabilities: list[str],
                          payload: dict[str, Any] | None = None) -> dict[str, Any]:
        capabilities = sorted(set(required_capabilities))
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("Agent task payload must be an object")
        payload_json = json.dumps(payload or {}, ensure_ascii=False)
        with self._session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO agent_tasks(task_id,source_agent,target_agent,required_capabilities_json,status,payload_json) "
                "VALUES(?,?,?,?, 'queued', ?)",
                (task_id, source_agent, target_agent, json.dumps(capabilities), payload_json),
            )
            self._insert_task_event(conn, task_id, "task.queued", {
                "task_id": task_id, "source_agent": source_agent,
                "target_agent": target_agent, "required_capabilities": capabilities,
            })
            row = conn.execute("SELECT * FROM agent_tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._agent_task_row(row)

    def claim_agent_task(self, worker_id: str, lease_seconds: int = 60,
                         max_attempts: int = 5, task_id: str | None = None) -> dict[str, Any] | None:
        if not worker_id or len(worker_id) > 128:
            raise ValueError("Invalid worker identity")
        if not 5 <= lease_seconds <= 3600 or not 1 <= max_attempts <= 20:
            raise ValueError("Invalid lease or retry limit")
        now = int(time.time())
        with self._session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            query = (
                "SELECT * FROM agent_tasks WHERE attempts < ? AND "
                "(status='queued' OR (status='running' AND lease_expires_at IS NOT NULL AND lease_expires_at<=?))"
            )
            params: tuple[Any, ...] = (max_attempts, now)
            if task_id is not None:
                query += " AND task_id=?"
                params += (task_id,)
            query += " ORDER BY created_at,task_id LIMIT 1"
            row = conn.execute(query, params).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE agent_tasks SET status='running',worker_id=?,lease_expires_at=?,attempts=attempts+1,"
                "error_code=NULL,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE task_id=?",
                (worker_id, now + lease_seconds, row["task_id"]),
            )
            self._insert_task_event(conn, row["task_id"], "task.claimed", {
                "task_id": row["task_id"], "worker_id": worker_id,
                "attempt": row["attempts"] + 1, "lease_expires_at": now + lease_seconds,
            })
            claimed = conn.execute("SELECT * FROM agent_tasks WHERE task_id=?", (row["task_id"],)).fetchone()
        return self._agent_task_row(claimed)

    def renew_agent_task_lease(self, task_id: str, worker_id: str,
                               lease_seconds: int = 60) -> bool:
        if not 5 <= lease_seconds <= 3600:
            raise ValueError("Invalid lease duration")
        now = int(time.time())
        with self._session() as conn:
            cursor = conn.execute(
                "UPDATE agent_tasks SET lease_expires_at=?,"
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE task_id=? AND status='running' AND worker_id=? AND lease_expires_at>?",
                (now + lease_seconds, task_id, worker_id, now),
            )
            return cursor.rowcount == 1

    def recover_expired_agent_tasks(self, max_attempts: int = 5) -> int:
        now = int(time.time())
        with self._session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT task_id,attempts FROM agent_tasks WHERE status='running' "
                "AND lease_expires_at IS NOT NULL AND lease_expires_at<=?",
                (now,),
            ).fetchall()
            recovered = 0
            for row in rows:
                if row["attempts"] >= max_attempts:
                    conn.execute(
                        "UPDATE agent_tasks SET status='failed',worker_id=NULL,lease_expires_at=NULL,"
                        "error_code='worker_lease_expired',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                        "WHERE task_id=? AND status='running' AND lease_expires_at<=?",
                        (row["task_id"], now),
                    )
                    self._insert_task_event(conn, row["task_id"], "task.failed", {
                        "task_id": row["task_id"], "error_code": "worker_lease_expired",
                    })
                else:
                    conn.execute(
                        "UPDATE agent_tasks SET status='queued',worker_id=NULL,lease_expires_at=NULL,"
                        "error_code='worker_lease_expired',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                        "WHERE task_id=? AND status='running' AND lease_expires_at<=?",
                        (row["task_id"], now),
                    )
                    self._insert_task_event(conn, row["task_id"], "task.requeued", {
                        "task_id": row["task_id"], "attempts": row["attempts"],
                    })
                recovered += 1
            return recovered

    def claim_task_outbox(self, worker_id: str, limit: int = 25,
                          lease_seconds: int = 60, max_attempts: int = 10) -> list[dict[str, Any]]:
        if not worker_id or len(worker_id) > 128:
            raise ValueError("Invalid worker identity")
        if not 1 <= limit <= 100 or not 5 <= lease_seconds <= 3600 or not 1 <= max_attempts <= 50:
            raise ValueError("Invalid outbox claim limits")
        now = int(time.time())
        with self._session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE agent_task_outbox SET dead_letter=1,status='pending',lease_owner=NULL,lease_expires_at=NULL "
                "WHERE status='leased' AND lease_expires_at<=? AND attempts>=?",
                (now, max_attempts),
            )
            rows = conn.execute(
                "SELECT event_id FROM agent_task_outbox WHERE dead_letter=0 AND attempts<? AND ("
                "(status='pending' AND available_at<=?) OR "
                "(status='leased' AND lease_expires_at<=?)) "
                "ORDER BY created_at,event_id LIMIT ?",
                (max_attempts, now, now, limit),
            ).fetchall()
            ids = [row["event_id"] for row in rows]
            for event_id in ids:
                conn.execute(
                    "UPDATE agent_task_outbox SET status='leased',lease_owner=?,"
                    "lease_expires_at=?,attempts=attempts+1 WHERE event_id=?",
                    (worker_id, now + lease_seconds, event_id),
                )
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            claimed = conn.execute(
                f"SELECT * FROM agent_task_outbox WHERE event_id IN ({placeholders}) "
                "ORDER BY created_at,event_id", ids,
            ).fetchall()
        return [dict(row, payload=json.loads(row["payload_json"])) for row in claimed]

    def acknowledge_task_outbox(self, event_id: str, worker_id: str) -> bool:
        with self._session() as conn:
            cursor = conn.execute(
                "UPDATE agent_task_outbox SET status='published',lease_owner=NULL,lease_expires_at=NULL "
                "WHERE event_id=? AND status='leased' AND lease_owner=? AND lease_expires_at>?",
                (event_id, worker_id, int(time.time())),
            )
            return cursor.rowcount == 1

    def retry_task_outbox(self, event_id: str, worker_id: str, delay_seconds: int = 5) -> bool:
        if not 0 <= delay_seconds <= 3600:
            raise ValueError("Invalid retry delay")
        with self._session() as conn:
            cursor = conn.execute(
                "UPDATE agent_task_outbox SET status='pending',lease_owner=NULL,lease_expires_at=NULL,"
                "available_at=?,attempts=attempts WHERE event_id=? AND status='leased' "
                "AND lease_owner=? AND lease_expires_at>?",
                (int(time.time()) + delay_seconds, event_id, worker_id, int(time.time())),
            )
            return cursor.rowcount == 1

    def update_agent_task(self, task_id: str, status: str, connector_id: str | None = None,
                          provider: str | None = None, error_code: str | None = None,
                          worker_id: str | None = None,
                          result: dict[str, Any] | None = None) -> dict[str, Any] | None:
        allowed = {"queued", "running", "succeeded", "failed", "cancelled"}
        if status not in allowed:
            raise ValueError("Invalid agent task status")
        with self._session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT * FROM agent_tasks WHERE task_id=?", (task_id,)).fetchone()
            if current is None:
                return None
            if worker_id is not None:
                if current["worker_id"] != worker_id:
                    raise ValueError("Worker does not own this task lease")
                if current["lease_expires_at"] is None or current["lease_expires_at"] <= int(time.time()):
                    raise ValueError("Worker task lease has expired")
            transitions = {
                "queued": {"running", "failed", "cancelled"},
                "running": {"succeeded", "failed", "cancelled", "queued"},
                "succeeded": set(), "failed": set(), "cancelled": set(),
            }
            if status != current["status"] and status not in transitions[current["status"]]:
                raise ValueError("Invalid agent task state transition")
            conn.execute(
                "UPDATE agent_tasks SET status=?,connector_id=COALESCE(?,connector_id),"
                "provider=COALESCE(?,provider),error_code=?,result_json=COALESCE(?,result_json),"
                "worker_id=CASE WHEN ? IN ('succeeded','failed','cancelled','queued') THEN NULL ELSE worker_id END,"
                "lease_expires_at=CASE WHEN ? IN ('succeeded','failed','cancelled','queued') THEN NULL ELSE lease_expires_at END,"
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE task_id=?",
                (status, connector_id, provider, error_code,
                 json.dumps(result, ensure_ascii=False) if result is not None else None,
                 status, status, task_id),
            )
            self._insert_task_event(conn, task_id, "task." + status, {
                "task_id": task_id, "status": status, "connector_id": connector_id,
                "provider": provider, "error_code": error_code,
            })
            row = conn.execute("SELECT * FROM agent_tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._agent_task_row(row)

    @staticmethod
    def _agent_task_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["required_capabilities"] = json.loads(item.pop("required_capabilities_json"))
        item["payload"] = json.loads(item.pop("payload_json", "{}"))
        item["result"] = json.loads(item["result_json"]) if item.get("result_json") else None
        item.pop("result_json", None)
        return item

    def list_agent_tasks(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("Task list limit must be between 1 and 100")
        allowed = {"queued", "running", "succeeded", "failed", "cancelled"}
        if status is not None and status not in allowed:
            raise ValueError("Invalid task status filter")
        with self._session() as conn:
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM agent_tasks ORDER BY created_at DESC,task_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_tasks WHERE status=? ORDER BY created_at DESC,task_id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
        return [self._agent_task_row(row) for row in rows]

    def agent_queue_status(self) -> dict[str, Any]:
        with self._session() as conn:
            task_rows = conn.execute(
                "SELECT status,COUNT(*) AS count FROM agent_tasks GROUP BY status"
            ).fetchall()
            outbox_rows = conn.execute(
                "SELECT status,COUNT(*) AS count FROM agent_task_outbox GROUP BY status"
            ).fetchall()
            dead_letters = conn.execute(
                "SELECT COUNT(*) FROM agent_task_outbox WHERE dead_letter=1"
            ).fetchone()[0]
            oldest_pending = conn.execute(
                "SELECT MIN(created_at) FROM agent_task_outbox WHERE status='pending' AND dead_letter=0"
            ).fetchone()[0]
        return {
            "tasks": {row["status"]: row["count"] for row in task_rows},
            "outbox": {row["status"]: row["count"] for row in outbox_rows},
            "dead_letter_count": dead_letters,
            "oldest_pending_event_at": oldest_pending,
        }

    def get_agent_task(self, task_id: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM agent_tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._agent_task_row(row) if row else None

    def approved_tools(self) -> set[str]:
        with self._session() as conn:
            rows = conn.execute("SELECT name FROM tool_permissions WHERE approved=1").fetchall()
        return {row["name"] for row in rows}

    def set_tool_approval(self, name: str, approved: bool) -> None:
        with self._session() as conn:
            conn.execute(
                "INSERT INTO tool_permissions(name,approved,updated_at) VALUES(?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now')) "
                "ON CONFLICT(name) DO UPDATE SET approved=excluded.approved,updated_at=excluded.updated_at",
                (name, int(approved)),
            )
            conn.execute("INSERT INTO tool_audit(tool_name,outcome) VALUES(?,?)",
                         (name, "owner_approved" if approved else "owner_revoked"))

    def audit_tool(self, name: str, outcome: str) -> None:
        with self._session() as conn:
            conn.execute("INSERT INTO tool_audit(tool_name,outcome) VALUES(?,?)", (name, outcome))

    def list_tool_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute("SELECT id,tool_name,outcome,created_at FROM tool_audit ORDER BY id DESC LIMIT ?",
                                (max(1, min(limit, 500)),)).fetchall()
        return [dict(row) for row in rows]


    def request_integration_approval(self, integration_id: str, version: str,
                                     manifest_digest: str, actor: str) -> dict[str, Any]:
        if not all(isinstance(v, str) and v.strip() for v in
                   (integration_id, version, manifest_digest, actor)):
            raise ValueError("Invalid integration approval request")
        with self._session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR IGNORE INTO integration_approvals "
                "(integration_id,version,manifest_digest,requested_by,status) "
                "VALUES(?,?,?,?,'pending')",
                (integration_id, version, manifest_digest, actor),
            )
            row = conn.execute(
                "SELECT * FROM integration_approvals WHERE integration_id=? AND version=? AND manifest_digest=?",
                (integration_id, version, manifest_digest),
            ).fetchone()
            conn.execute(
                "INSERT INTO integration_audit(integration_id,version,action,actor,reason,manifest_digest) "
                "VALUES(?,?, 'approval_requested', ?, '', ?)",
                (integration_id, version, actor, manifest_digest),
            )
        return dict(row)

    def decide_integration_approval(self, integration_id: str, version: str,
                                    manifest_digest: str, approved: bool,
                                    actor: str, reason: str = "") -> dict[str, Any] | None:
        if not isinstance(approved, bool) or not actor or len(reason) > 1000:
            raise ValueError("Invalid integration approval decision")
        with self._session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM integration_approvals WHERE integration_id=? AND version=? AND manifest_digest=?",
                (integration_id, version, manifest_digest),
            ).fetchone()
            if row is None:
                return None
            if row["status"] != "pending":
                raise ValueError("Integration approval is already decided")
            status = "approved" if approved else "rejected"
            conn.execute(
                "UPDATE integration_approvals SET status=?,decision_by=?,decision_reason=?,"
                "decided_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE integration_id=? AND version=? AND manifest_digest=? AND status='pending'",
                (status, actor, reason, integration_id, version, manifest_digest),
            )
            conn.execute(
                "INSERT INTO integration_audit(integration_id,version,action,actor,reason,manifest_digest) "
                "VALUES(?,?,?,?,?,?)",
                (integration_id, version, "approved" if approved else "rejected",
                 actor, reason, manifest_digest),
            )
            updated = conn.execute(
                "SELECT * FROM integration_approvals WHERE integration_id=? AND version=? AND manifest_digest=?",
                (integration_id, version, manifest_digest),
            ).fetchone()
        return dict(updated)

    def list_integration_approvals(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM integration_approvals ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_integration_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM integration_audit ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [dict(row) for row in rows]


    def record_integration_event(self, integration_id: str, version: str, action: str,
                                 actor: str, reason: str, manifest_digest: str) -> None:
        """Append an integration lifecycle event to the audit trail."""
        values = (integration_id, version, action, actor, reason, manifest_digest)
        if any(not isinstance(value, str) for value in values):
            raise ValueError("Invalid integration audit event")
        if not all(value.strip() for value in (integration_id, version, action, actor, manifest_digest)):
            raise ValueError("Integration audit identifiers cannot be blank")
        if len(reason) > 1000:
            raise ValueError("Integration audit reason is too long")
        with self._session() as conn:
            conn.execute(
                "INSERT INTO integration_audit(integration_id,version,action,actor,reason,manifest_digest) "
                "VALUES(?,?,?,?,?,?)", values,
            )


    def request_integration_activation(self, integration_id: str, version: str,
                                       manifest_digest: str, actor: str) -> dict[str, Any]:
        if not all(isinstance(v, str) and v.strip() for v in
                   (integration_id, version, manifest_digest, actor)):
            raise ValueError("Invalid integration activation request")
        with self._session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR IGNORE INTO integration_activation_approvals "
                "(integration_id,version,manifest_digest,requested_by,status) "
                "VALUES(?,?,?,?,'pending')",
                (integration_id, version, manifest_digest, actor),
            )
            row = conn.execute(
                "SELECT * FROM integration_activation_approvals "
                "WHERE integration_id=? AND version=? AND manifest_digest=?",
                (integration_id, version, manifest_digest),
            ).fetchone()
            conn.execute(
                "INSERT INTO integration_audit(integration_id,version,action,actor,reason,manifest_digest) "
                "VALUES(?,?, 'activation_requested', ?, '', ?)",
                (integration_id, version, actor, manifest_digest),
            )
        return dict(row)

    def decide_integration_activation(self, integration_id: str, version: str,
                                      manifest_digest: str, approved: bool,
                                      actor: str, reason: str = "") -> dict[str, Any] | None:
        if not isinstance(approved, bool) or not isinstance(actor, str) or not actor or len(reason) > 1000:
            raise ValueError("Invalid integration activation decision")
        with self._session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM integration_activation_approvals "
                "WHERE integration_id=? AND version=? AND manifest_digest=?",
                (integration_id, version, manifest_digest),
            ).fetchone()
            if row is None:
                return None
            if row["status"] != "pending":
                raise ValueError("Integration activation approval is already decided")
            status = "approved" if approved else "rejected"
            conn.execute(
                "UPDATE integration_activation_approvals SET status=?,decision_by=?,decision_reason=?,"
                "decided_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE integration_id=? AND version=? AND manifest_digest=? AND status='pending'",
                (status, actor, reason, integration_id, version, manifest_digest),
            )
            conn.execute(
                "INSERT INTO integration_audit(integration_id,version,action,actor,reason,manifest_digest) "
                "VALUES(?,?,?,?,?,?)",
                (integration_id, version, "activation_approved" if approved else "activation_rejected",
                 actor, reason, manifest_digest),
            )
            updated = conn.execute(
                "SELECT * FROM integration_activation_approvals "
                "WHERE integration_id=? AND version=? AND manifest_digest=?",
                (integration_id, version, manifest_digest),
            ).fetchone()
        return dict(updated)

    def list_integration_activation_approvals(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM integration_activation_approvals ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [dict(row) for row in rows]
