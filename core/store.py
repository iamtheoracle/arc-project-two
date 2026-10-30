"""Private, persistent storage for Oracle Arc conversations, memories, and tool permissions."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
import uuid
from pathlib import Path
from typing import Any


class ArcStore:
    def __init__(self, path: str | Path | None = None):
        configured = path or os.environ.get("ORACLE_ARC_DB_PATH", "data/oracle_arc.sqlite3")
        self.path = Path(configured)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._initialize()
        if str(self.path) != ":memory:":
            try:
                self.path.chmod(0o600)
            except OSError:
                pass

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10)
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
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);
                CREATE TABLE IF NOT EXISTS user_profile (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    profile_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
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
            """)

    def create_conversation(self, title: str = "") -> str:
        conversation_id = str(uuid.uuid4())
        with self._session() as conn:
            conn.execute("INSERT INTO conversations(id,title) VALUES(?,?)", (conversation_id, title[:160]))
        return conversation_id

    def conversation_exists(self, conversation_id: str) -> bool:
        with self._session() as conn:
            return conn.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone() is not None

    def add_message(self, conversation_id: str, role: str, content: str) -> None:
        if role not in ("user", "assistant"):
            raise ValueError("Unsupported message role")
        with self._session() as conn:
            conn.execute("INSERT INTO messages(conversation_id,role,content) VALUES(?,?,?)",
                         (conversation_id, role, content))
            conn.execute("UPDATE conversations SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                         (conversation_id,))

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
