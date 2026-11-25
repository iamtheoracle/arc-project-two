"""SPARK: authenticated, scoped, auditable memory.

Every memory lives in a *space* ("<app>/<namespace>", e.g. "unibud/flow") and a *scope*
(personal | application | conversation | task). A caller can only touch spaces its agent is allowed,
and only inside its own application. Reading another space for the same user requires an explicit,
revocable share grant from that user. Nothing is shared implicitly because two services use Oracle Arc.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from .types import DataClass, PermissionDenied, Principal, ValidationError

SCOPES = ("personal", "application", "conversation", "task")
_WORD = re.compile(r"[a-z0-9₦$€£]+")


def _tokens(text: str) -> list:
    return [w for w in _WORD.findall(text.lower()) if len(w) > 1]


@dataclass
class Memory:
    id: str
    space: str
    scope: str
    owner: str
    content: str
    data_class: DataClass
    created: float
    expires: Optional[float]
    score: float = 0.0


class SparkMemory:
    def __init__(self, path: str = ":memory:", audit=None, clock=time.time):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._audit, self._clock = audit, clock
        self._db.execute("CREATE TABLE IF NOT EXISTS mem (id TEXT PRIMARY KEY, space TEXT, scope TEXT, owner TEXT,"
                         " content TEXT, dclass INTEGER, created REAL, expires REAL,"
                         " purpose TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1)")
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(mem)")}
        if "purpose" not in cols:                          # upgrade a database created before A10
            self._db.execute("ALTER TABLE mem ADD COLUMN purpose TEXT NOT NULL DEFAULT ''")
        if "version" not in cols:
            self._db.execute("ALTER TABLE mem ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
        self._db.execute("CREATE TABLE IF NOT EXISTS share (user_id TEXT, from_space TEXT, to_space TEXT,"
                         " PRIMARY KEY (user_id, from_space, to_space))")
        self._db.commit()

    # ---- helpers -----------------------------------------------------------------------------
    @staticmethod
    def space_of(p: Principal, namespace: str) -> str:
        return f"{p.app_id}/{namespace}"

    def _check_ns(self, p: Principal, namespace: str, allowed_namespaces) -> str:
        if namespace not in allowed_namespaces:
            raise PermissionDenied(f"agent may not use memory namespace '{namespace}'")
        return self.space_of(p, namespace)

    def _owner(self, p: Principal, scope: str, scope_id: str) -> str:
        if scope == "personal":
            return p.user_id
        if scope == "application":
            return p.app_id
        if not scope_id:
            raise ValidationError(f"{scope} memory requires a scope id")
        return f"{p.user_id}:{scope_id}"       # conversation/task ids are private to the user

    # ---- write -------------------------------------------------------------------------------
    def remember(self, p: Principal, namespace: str, allowed_namespaces, content: str, scope: str = "personal",
                 scope_id: str = "", data_class: DataClass = DataClass.PERSONAL, ttl_s: float = None,
                 purpose: str = "") -> str:
        if scope not in SCOPES:
            raise ValidationError(f"unknown scope: {scope}")
        if not content or len(content) > 8000:
            raise ValidationError("memory content must be 1..8000 characters")
        if not isinstance(purpose, str) or len(purpose) > 240:
            raise ValidationError("purpose must be at most 240 characters")
        if scope == "task" and ttl_s is None:
            ttl_s = 3600.0                                     # temporary task context always expires
        space = self._check_ns(p, namespace, allowed_namespaces)
        mid = uuid.uuid4().hex
        now = self._clock()
        with self._lock:
            self._db.execute("INSERT INTO mem (id,space,scope,owner,content,dclass,created,expires,purpose)"
                             " VALUES (?,?,?,?,?,?,?,?,?)",
                             (mid, space, scope, self._owner(p, scope, scope_id), content, int(data_class), now,
                              now + ttl_s if ttl_s else None, purpose))
            self._db.commit()
        if self._audit:
            self._audit.append("memory.write", app_id=p.app_id, user_id=p.user_id, space=space, scope=scope, id=mid)
        return mid

    # ---- sharing -----------------------------------------------------------------------------
    def share(self, p: Principal, from_namespace: str, to_namespace: str) -> None:
        """The *user* (not an agent) grants one space read access to another, within the same app."""
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO share VALUES (?,?,?)",
                             (p.user_id, self.space_of(p, from_namespace), self.space_of(p, to_namespace)))
            self._db.commit()
        if self._audit:
            self._audit.append("memory.share", app_id=p.app_id, user_id=p.user_id,
                               from_ns=from_namespace, to_ns=to_namespace)

    def unshare(self, p: Principal, from_namespace: str, to_namespace: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM share WHERE user_id=? AND from_space=? AND to_space=?",
                             (p.user_id, self.space_of(p, from_namespace), self.space_of(p, to_namespace)))
            self._db.commit()
        if self._audit:
            self._audit.append("memory.unshare", app_id=p.app_id, user_id=p.user_id,
                               from_ns=from_namespace, to_ns=to_namespace)

    def _readable_spaces(self, p: Principal, namespace: str) -> list:
        mine = self.space_of(p, namespace)
        rows = self._db.execute("SELECT from_space FROM share WHERE user_id=? AND to_space=?",
                                (p.user_id, mine)).fetchall()
        return [mine] + [r[0] for r in rows]

    # ---- read --------------------------------------------------------------------------------
    def recall(self, p: Principal, namespace: str, allowed_namespaces, query: str, k: int = 5,
               scope_ids=()) -> list:
        spaces = self._readable_spaces(p, self._check_ns(p, namespace, allowed_namespaces).split("/", 1)[1])
        owners = {p.user_id, p.app_id} | {f"{p.user_id}:{s}" for s in scope_ids}
        now = self._clock()
        q = ",".join("?" * len(spaces))
        o = ",".join("?" * len(owners))
        with self._lock:
            rows = self._db.execute(
                f"SELECT id,space,scope,owner,content,dclass,created,expires FROM mem WHERE space IN ({q}) "
                f"AND owner IN ({o}) AND (expires IS NULL OR expires > ?)", (*spaces, *owners, now)).fetchall()
        qt = set(_tokens(query))
        out = []
        for r in rows:
            toks = _tokens(r[4])
            overlap = len(qt & set(toks))
            if qt and overlap == 0:
                continue
            recency = 1.0 / (1.0 + (now - r[6]) / 86400.0)
            out.append(Memory(r[0], r[1], r[2], r[3], r[4], DataClass(r[5]), r[6], r[7],
                              score=overlap / (1 + len(toks)) ** 0.5 + 0.1 * recency))
        out.sort(key=lambda m: -m.score)
        if self._audit:
            self._audit.append("memory.read", app_id=p.app_id, user_id=p.user_id, space=self.space_of(p, namespace),
                               returned=len(out[:k]))
        return out[:k]

    # ---- user controls (A10). Exact owner matching only: user ids may contain LIKE wildcards. ----------
    @staticmethod
    def _user_owned_sql() -> str:
        # owner is the user id itself, or "<user id>:<conversation/task id>". Never use LIKE here.
        return "(owner = ? OR substr(owner, 1, ?) = ?) AND substr(space, 1, ?) = ?"

    @staticmethod
    def _user_owned_args(p: Principal) -> tuple:
        prefix = p.user_id + ":"
        app_prefix = p.app_id + "/"
        return p.user_id, len(prefix), prefix, len(app_prefix), app_prefix

    def list_memories(self, p: Principal, limit: int = 100) -> list:
        """What SPARK holds about this user in this application (never application-owned memory)."""
        limit = max(1, min(int(limit), 500))
        with self._lock:
            rows = self._db.execute(
                "SELECT id,space,scope,content,purpose,dclass,version,created,expires FROM mem WHERE "
                + self._user_owned_sql() + " AND (expires IS NULL OR expires > ?) ORDER BY created DESC, rowid DESC LIMIT ?",
                (*self._user_owned_args(p), self._clock(), limit)).fetchall()
        if self._audit:
            self._audit.append("memory.list", app_id=p.app_id, user_id=p.user_id, returned=len(rows))
        return [dict(id=r[0], space=r[1], scope=r[2], content=r[3], purpose=r[4], data_class=DataClass(r[5]).name,
                     version=r[6], created=r[7], expires=r[8]) for r in rows]

    def correct(self, p: Principal, memory_id: str, content: str) -> bool:
        if not isinstance(content, str) or not content or len(content) > 8000:
            raise ValidationError("memory content must be 1..8000 characters")
        with self._lock:
            cur = self._db.execute("UPDATE mem SET content=?, version=version+1 WHERE id=? AND "
                                   + self._user_owned_sql(), (content, memory_id, *self._user_owned_args(p)))
            self._db.commit()
        if self._audit:
            self._audit.append("memory.correct", app_id=p.app_id, user_id=p.user_id, id=memory_id,
                               changed=cur.rowcount > 0)
        return cur.rowcount > 0

    def forget(self, p: Principal, memory_id: str) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM mem WHERE id=? AND " + self._user_owned_sql(),
                                   (memory_id, *self._user_owned_args(p)))
            self._db.commit()
        if self._audit:
            self._audit.append("memory.forget", app_id=p.app_id, user_id=p.user_id, id=memory_id,
                               removed=cur.rowcount > 0)
        return cur.rowcount > 0

    def forget_all(self, p: Principal) -> int:
        """Delete everything this user has in this application, including their share grants."""
        with self._lock:
            cur = self._db.execute("DELETE FROM mem WHERE " + self._user_owned_sql(), self._user_owned_args(p))
            self._db.execute("DELETE FROM share WHERE user_id=? AND substr(from_space,1,?)=?",
                             (p.user_id, len(p.app_id) + 1, p.app_id + "/"))
            self._db.commit()
        if self._audit:
            self._audit.append("memory.forget_all", app_id=p.app_id, user_id=p.user_id, removed=cur.rowcount)
        return cur.rowcount

    def purge_expired(self) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM mem WHERE expires IS NOT NULL AND expires <= ?", (self._clock(),))
            self._db.commit()
        return cur.rowcount

    def close(self) -> None:
        self._db.close()
