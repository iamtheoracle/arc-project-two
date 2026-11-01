"""Durable, principal-scoped voice session lifecycle and event journal.

Raw audio and generated audio are deliberately not stored here. This store records
only lifecycle metadata and event details; callers must apply capability checks.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
import time
import uuid
from pathlib import Path
from typing import Any

TERMINAL = {"cancelled", "failed", "completed"}
STATES = {
    "created", "capturing", "uploaded", "transcribing", "awaiting_model",
    "synthesizing", "ready", "playing", "interrupted", "cancelled",
    "failed", "completed",
}
_ALLOWED = {
    "created": {"capturing", "uploaded", "cancelled", "failed"},
    "capturing": {"uploaded", "cancelled", "failed"},
    "uploaded": {"transcribing", "cancelled", "failed"},
    "transcribing": {"awaiting_model", "cancelled", "failed"},
    "awaiting_model": {"synthesizing", "completed", "cancelled", "failed"},
    "synthesizing": {"ready", "cancelled", "failed"},
    "ready": {"playing", "completed", "cancelled"},
    "playing": {"completed", "interrupted", "cancelled", "failed"},
    "interrupted": {"capturing", "completed", "cancelled", "failed"},
    "cancelled": set(), "failed": set(), "completed": set(),
}


class VoiceSessionError(RuntimeError):
    pass


class VoiceSessionStore:
    def __init__(self, database_path: str | Path):
        self.path = str(database_path)
        if self.path == ":memory:":
            raise ValueError("VoiceSessionStore requires a durable database path")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.initialize()

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        with self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS arc_voice_sessions (
              session_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
              application_id TEXT NOT NULL, principal_id TEXT NOT NULL,
              state TEXT NOT NULL, created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL, version INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_voice_session_scope
              ON arc_voice_sessions(tenant_id,application_id,principal_id,created_at);
            CREATE TABLE IF NOT EXISTS arc_voice_events (
              event_id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
              application_id TEXT NOT NULL, principal_id TEXT NOT NULL,
              event_type TEXT NOT NULL, state TEXT NOT NULL,
              details_json TEXT NOT NULL, created_at INTEGER NOT NULL,
              FOREIGN KEY(session_id) REFERENCES arc_voice_sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_voice_event_scope
              ON arc_voice_events(session_id,event_id);
            """)

    @staticmethod
    def _scope(identity):
        return (identity.tenant_id, identity.application_id, identity.principal_id)

    def _event(self, db, identity, session_id, event_type, state, details=None):
        db.execute("""INSERT INTO arc_voice_events
          (session_id,tenant_id,application_id,principal_id,event_type,state,details_json,created_at)
          VALUES(?,?,?,?,?,?,?,?)""",
          (session_id, *self._scope(identity), event_type, state,
           json.dumps(details or {}, separators=(",", ":"), ensure_ascii=False), int(time.time())))

    def create(self, identity) -> dict[str, Any]:
        now = int(time.time())
        session_id = "vcs_" + uuid.uuid4().hex
        with self._db() as db:
            db.execute("""INSERT INTO arc_voice_sessions
              (session_id,tenant_id,application_id,principal_id,state,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?)""",
              (session_id, *self._scope(identity), "created", now, now))
            self._event(db, identity, session_id, "session.created", "created")
        return {"session_id": session_id, "state": "created", "version": 1,
                "created_at": now, "raw_audio_retained": False}

    def get(self, identity, session_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("""SELECT session_id,state,created_at,updated_at,version
              FROM arc_voice_sessions WHERE session_id=? AND tenant_id=?
              AND application_id=? AND principal_id=?""",
              (session_id, *self._scope(identity))).fetchone()
        return dict(row) if row else None

    def transition(self, identity, session_id: str, target: str,
                   event_type: str | None = None, details: dict | None = None) -> dict[str, Any]:
        if target not in STATES:
            raise ValueError("Unknown voice session state")
        now = int(time.time())
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT state,version FROM arc_voice_sessions
              WHERE session_id=? AND tenant_id=? AND application_id=? AND principal_id=?""",
              (session_id, *self._scope(identity))).fetchone()
            if row is None:
                raise KeyError("Voice session not found in this principal scope")
            current = row["state"]
            if current == target and target == "cancelled":
                return {"session_id": session_id, "state": current,
                        "version": row["version"], "idempotent": True}
            if target not in _ALLOWED[current]:
                raise VoiceSessionError(f"Invalid voice session transition: {current} -> {target}")
            version = row["version"] + 1
            changed = db.execute("""UPDATE arc_voice_sessions SET state=?,updated_at=?,version=?
              WHERE session_id=? AND version=?""",
              (target, now, version, session_id, row["version"]))
            if changed.rowcount != 1:
                raise VoiceSessionError("Concurrent voice session update; reload and retry")
            self._event(db, identity, session_id, event_type or f"session.{target}",
                        target, details)
        return {"session_id": session_id, "state": target, "version": version,
                "updated_at": now, "idempotent": False}

    def cancel(self, identity, session_id: str) -> dict[str, Any]:
        existing = self.get(identity, session_id)
        if existing is None:
            raise KeyError("Voice session not found in this principal scope")
        if existing["state"] in TERMINAL:
            return {"session_id": session_id, "state": existing["state"],
                    "version": existing["version"], "idempotent": True}
        return self.transition(identity, session_id, "cancelled", "session.cancelled")

    def events(self, identity, session_id: str, after: int = 0, limit: int = 100) -> list[dict]:
        if after < 0 or not 1 <= limit <= 200:
            raise ValueError("Invalid event cursor or limit")
        with self._db() as db:
            owned = db.execute("""SELECT 1 FROM arc_voice_sessions WHERE session_id=?
              AND tenant_id=? AND application_id=? AND principal_id=?""",
              (session_id, *self._scope(identity))).fetchone()
            if not owned:
                raise KeyError("Voice session not found in this principal scope")
            rows = db.execute("""SELECT event_id,event_type,state,details_json,created_at
              FROM arc_voice_events WHERE session_id=? AND tenant_id=? AND application_id=?
              AND principal_id=? AND event_id>? ORDER BY event_id LIMIT ?""",
              (session_id, *self._scope(identity), after, limit)).fetchall()
        return [{"event_id": r["event_id"], "event_type": r["event_type"],
                 "state": r["state"], "details": json.loads(r["details_json"]),
                 "created_at": r["created_at"]} for r in rows]
