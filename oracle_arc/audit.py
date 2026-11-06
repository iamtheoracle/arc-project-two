"""Append-only, hash-chained audit trail. Tampering with any stored row breaks verification."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from typing import Any, Optional

_SECRET_KEYS = ("secret", "token", "password", "api_key", "apikey", "authorization", "key")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[redacted]" if any(s in str(k).lower() for s in _SECRET_KEYS) else redact(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


class AuditLog:
    GENESIS = "0" * 64

    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, event TEXT,"
            " app_id TEXT, user_id TEXT, agent TEXT, detail TEXT, prev TEXT, hash TEXT)")
        self._db.commit()

    def append(self, event: str, *, app_id: str = "", user_id: str = "", agent: str = "", **detail: Any) -> int:
        with self._lock:
            row = self._db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
            prev = row[0] if row else self.GENESIS
            ts = time.time()
            body = _canon(redact(detail))
            digest = hashlib.sha256(
                (prev + _canon([ts, event, app_id, user_id, agent, body])).encode()).hexdigest()
            cur = self._db.execute(
                "INSERT INTO audit (ts,event,app_id,user_id,agent,detail,prev,hash) VALUES (?,?,?,?,?,?,?,?)",
                (ts, event, app_id, user_id, agent, body, prev, digest))
            self._db.commit()
            return cur.lastrowid

    def events(self, event: Optional[str] = None) -> list:
        q = "SELECT seq,ts,event,app_id,user_id,agent,detail FROM audit"
        args: tuple = ()
        if event:
            q += " WHERE event=?"
            args = (event,)
        rows = self._db.execute(q + " ORDER BY seq", args).fetchall()
        return [dict(seq=r[0], ts=r[1], event=r[2], app_id=r[3], user_id=r[4], agent=r[5],
                     detail=json.loads(r[6])) for r in rows]

    def verify(self) -> bool:
        prev = self.GENESIS
        for seq, ts, event, app_id, user_id, agent, detail, p, h in self._db.execute(
                "SELECT seq,ts,event,app_id,user_id,agent,detail,prev,hash FROM audit ORDER BY seq"):
            expect = hashlib.sha256((prev + _canon([ts, event, app_id, user_id, agent, detail])).encode()).hexdigest()
            if p != prev or h != expect:
                return False
            prev = h
        return True

    def close(self) -> None:
        self._db.close()
