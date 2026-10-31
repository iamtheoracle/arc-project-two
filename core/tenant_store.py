"""Tenant/application scoped data plane, isolated from legacy owner tables.

All reads and writes require a trusted RequestIdentity. Scope is always included in SQL
predicates; caller-supplied IDs never select a tenant or application.
"""
from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
import uuid
from typing import Any
from .tenant_identity import RequestIdentity


class TenantStore:
    def __init__(self, database_path: str):
        self.database_path = database_path
        with self._session() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS arc_scoped_conversations(
              tenant_id TEXT NOT NULL, application_id TEXT NOT NULL, principal_id TEXT NOT NULL,
              conversation_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY(tenant_id,application_id,conversation_id)
            );
            CREATE TABLE IF NOT EXISTS arc_scoped_messages(
              tenant_id TEXT NOT NULL, application_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
              message_id TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','assistant')),
              content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY(tenant_id,application_id,message_id),
              FOREIGN KEY(tenant_id,application_id,conversation_id)
                REFERENCES arc_scoped_conversations(tenant_id,application_id,conversation_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS arc_scoped_memories(
              tenant_id TEXT NOT NULL, application_id TEXT NOT NULL, principal_id TEXT NOT NULL,
              memory_id TEXT NOT NULL, category TEXT NOT NULL, content TEXT NOT NULL,
              tags_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY(tenant_id,application_id,memory_id)
            );
            CREATE TABLE IF NOT EXISTS arc_memory_grants(
              grant_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
              source_application_id TEXT NOT NULL, destination_application_id TEXT NOT NULL,
              principal_id TEXT NOT NULL, categories_json TEXT NOT NULL,
              purpose TEXT NOT NULL, expires_at INTEGER NOT NULL, revoked_at INTEGER,
              CHECK(source_application_id <> destination_application_id)
            );
            """)
            db.commit()

    def _connect(self):
        db=sqlite3.connect(self.database_path,timeout=10)
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @contextmanager
    def _session(self):
        db = self._connect()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _require(identity: RequestIdentity, capability: str):
        if capability not in identity.capabilities:
            raise PermissionError("Required application capability is not granted")

    def create_conversation(self, identity: RequestIdentity, title: str = "") -> str:
        self._require(identity, "conversation.write")
        cid=uuid.uuid4().hex
        with self._session() as db:
            db.execute("INSERT INTO arc_scoped_conversations VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)",
                (identity.tenant_id,identity.application_id,identity.principal_id,cid,title[:160]))
            db.commit()
        return cid

    def add_message(self, identity: RequestIdentity, conversation_id: str, role: str, content: str) -> str:
        self._require(identity, "conversation.write")
        if role not in {"user","assistant"}: raise ValueError("Unsupported message role")
        mid=uuid.uuid4().hex
        with self._session() as db:
            parent=db.execute("SELECT 1 FROM arc_scoped_conversations WHERE tenant_id=? AND application_id=? AND principal_id=? AND conversation_id=?",
                (identity.tenant_id,identity.application_id,identity.principal_id,conversation_id)).fetchone()
            if parent is None: raise LookupError("Conversation not found")
            db.execute("INSERT INTO arc_scoped_messages VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                (identity.tenant_id,identity.application_id,conversation_id,mid,role,content))
            db.commit()
        return mid

    def get_messages(self, identity: RequestIdentity, conversation_id: str) -> list[dict[str,Any]]:
        self._require(identity, "conversation.read")
        with self._session() as db:
            parent=db.execute("SELECT 1 FROM arc_scoped_conversations WHERE tenant_id=? AND application_id=? AND principal_id=? AND conversation_id=?",
                (identity.tenant_id,identity.application_id,identity.principal_id,conversation_id)).fetchone()
            if parent is None: raise LookupError("Conversation not found")
            rows=db.execute("SELECT role,content,created_at FROM arc_scoped_messages WHERE tenant_id=? AND application_id=? AND conversation_id=? ORDER BY created_at,message_id",
                (identity.tenant_id,identity.application_id,conversation_id)).fetchall()
        return [dict(row) for row in rows]

    def save_memory(self, identity: RequestIdentity, content: str, category: str="general", tags: list[str]|None=None) -> str:
        self._require(identity, "memory.write")
        if category not in {"general","preferences","learning","projects","sensitive"}:
            raise ValueError("Unknown memory category")
        if category == "sensitive" and "memory.sensitive.write" not in identity.capabilities:
            raise PermissionError("Sensitive memory requires a separate capability")
        mid=uuid.uuid4().hex
        with self._session() as db:
            db.execute("INSERT INTO arc_scoped_memories VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                (identity.tenant_id,identity.application_id,identity.principal_id,mid,category,content,
                 json.dumps(tags or [],ensure_ascii=False)))
            db.commit()
        return mid

    def list_memories(self, identity: RequestIdentity, limit: int = 100) -> list[dict[str, Any]]:
        self._require(identity, "memory.read")
        if not 1 <= limit <= 500:
            raise ValueError("Memory list limit must be between 1 and 500")
        with self._session() as db:
            rows = db.execute(
                "SELECT memory_id,category,content,tags_json,created_at FROM arc_scoped_memories "
                "WHERE tenant_id=? AND application_id=? AND principal_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (identity.tenant_id, identity.application_id, identity.principal_id, limit),
            ).fetchall()
        result = []
        for row in rows:
            if row["category"] == "sensitive" and "memory.sensitive.read" not in identity.capabilities:
                continue
            result.append({"memory_id": row["memory_id"], "category": row["category"],
                           "content": row["content"], "tags": json.loads(row["tags_json"]),
                           "created_at": row["created_at"]})
        return result

    def update_memory(self, identity: RequestIdentity, memory_id: str,
                      content: str, category: str, tags: list[str] | None = None) -> bool:
        self._require(identity, "memory.write")
        if category not in {"general","preferences","learning","projects","sensitive"}:
            raise ValueError("Unknown memory category")
        if category == "sensitive" and "memory.sensitive.write" not in identity.capabilities:
            raise PermissionError("Sensitive memory requires a separate capability")
        with self._session() as db:
            cursor = db.execute(
                "UPDATE arc_scoped_memories SET content=?,category=?,tags_json=? "
                "WHERE tenant_id=? AND application_id=? AND principal_id=? AND memory_id=?",
                (content, category, json.dumps(tags or [], ensure_ascii=False),
                 identity.tenant_id, identity.application_id, identity.principal_id, memory_id),
            )
        return cursor.rowcount == 1

    def delete_memory(self, identity: RequestIdentity, memory_id: str) -> bool:
        self._require(identity, "memory.delete")
        with self._session() as db:
            cursor = db.execute(
                "DELETE FROM arc_scoped_memories WHERE tenant_id=? AND application_id=? "
                "AND principal_id=? AND memory_id=?",
                (identity.tenant_id, identity.application_id, identity.principal_id, memory_id),
            )
        return cursor.rowcount == 1

    def create_memory_grant(self, identity: RequestIdentity, destination_application_id: str,
                            categories: list[str], purpose: str, expires_at: int) -> str:
        self._require(identity, "memory.share")
        if not categories or not purpose.strip() or expires_at <= identity.issued_at:
            raise ValueError("A purpose, categories and future expiry are required")
        grant="grant_"+uuid.uuid4().hex
        with self._session() as db:
            dest=db.execute("SELECT 1 FROM arc_applications WHERE tenant_id=? AND application_id=? AND status='active'",
                (identity.tenant_id,destination_application_id)).fetchone()
            if not dest: raise LookupError("Destination application not found")
            db.execute("INSERT INTO arc_memory_grants VALUES(?,?,?,?,?,?,?, ?,NULL)",
                (grant,identity.tenant_id,identity.application_id,destination_application_id,
                 identity.principal_id,json.dumps(sorted(set(categories))),purpose.strip()[:500],expires_at))
            db.commit()
        return grant

    def revoke_memory_grant(self, identity: RequestIdentity, grant_id: str) -> bool:
        self._require(identity, "memory.share")
        with self._session() as db:
            cursor=db.execute("UPDATE arc_memory_grants SET revoked_at=unixepoch() WHERE grant_id=? AND tenant_id=? AND source_application_id=? AND principal_id=? AND revoked_at IS NULL",
                (grant_id,identity.tenant_id,identity.application_id,identity.principal_id))
            db.commit()
        return cursor.rowcount == 1

    def shared_memories(self, identity: RequestIdentity, source_application_id: str) -> list[dict[str,Any]]:
        self._require(identity, "memory.shared.read")
        with self._session() as db:
            grants=db.execute("SELECT categories_json FROM arc_memory_grants WHERE tenant_id=? AND source_application_id=? AND destination_application_id=? AND principal_id=? AND revoked_at IS NULL AND expires_at>unixepoch()",
                (identity.tenant_id,source_application_id,identity.application_id,identity.principal_id)).fetchall()
            allowed=set()
            for grant in grants: allowed.update(json.loads(grant["categories_json"]))
            if not allowed: return []
            placeholders=",".join("?" for _ in allowed)
            rows=db.execute(f"SELECT memory_id,category,content,tags_json FROM arc_scoped_memories WHERE tenant_id=? AND application_id=? AND principal_id=? AND category IN ({placeholders})",
                (identity.tenant_id,source_application_id,identity.principal_id,*sorted(allowed))).fetchall()
        return [{"memory_id":r["memory_id"],"category":r["category"],"content":r["content"],"tags":json.loads(r["tags_json"])} for r in rows]
