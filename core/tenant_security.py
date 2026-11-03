"""Trusted tenant/application identity and scoped SPARK memory primitives.

This module is additive. It does not convert the legacy owner API or legacy rows into
tenant-scoped data. Application credentials are opaque, hashed at rest, revocable, and
bound server-side to one tenant, application, principal, and capability set.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
import hmac
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class IdentityError(RuntimeError):
    pass


class AuthorizationError(IdentityError):
    pass


@dataclass(frozen=True)
class RequestIdentity:
    credential_id: str
    tenant_id: str
    application_id: str
    principal_id: str
    capabilities: frozenset[str]
    policy_version: int


class TenantSecurityStore:
    """Control-plane and scoped-memory repository on the existing SQLite database."""

    def __init__(self, database_path: str | Path):
        self.path = str(database_path)
        if self.path == ":memory:":
            raise ValueError("TenantSecurityStore requires a durable database path")
        Path(self.path).parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.initialize()
        try:
            Path(self.path).chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def _session(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        with self._session() as db:
            db.execute("CREATE TABLE IF NOT EXISTS arc_schema_migrations(version INTEGER PRIMARY KEY,applied_at INTEGER NOT NULL)")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS arc_tenants(
              tenant_id TEXT PRIMARY KEY, name TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('active','suspended','closed')),
              created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS arc_applications(
              application_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
              name TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','suspended','closed')),
              policy_version INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL,
              UNIQUE(tenant_id, application_id),
              FOREIGN KEY(tenant_id) REFERENCES arc_tenants(tenant_id)
            );
            CREATE TABLE IF NOT EXISTS arc_principals(
              principal_id TEXT PRIMARY KEY, status TEXT NOT NULL
              CHECK(status IN ('active','suspended','deleted')), created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS arc_credentials(
              credential_id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL UNIQUE,
              tenant_id TEXT NOT NULL, application_id TEXT NOT NULL, principal_id TEXT NOT NULL,
              capabilities_json TEXT NOT NULL, expires_at INTEGER, revoked_at INTEGER,
              created_at INTEGER NOT NULL, last_used_at INTEGER,
              FOREIGN KEY(tenant_id) REFERENCES arc_tenants(tenant_id),
              FOREIGN KEY(application_id) REFERENCES arc_applications(application_id),
              FOREIGN KEY(principal_id) REFERENCES arc_principals(principal_id)
            );
            CREATE INDEX IF NOT EXISTS idx_arc_credentials_scope
              ON arc_credentials(tenant_id,application_id,principal_id);
            CREATE TABLE IF NOT EXISTS arc_scoped_memories(
              memory_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, application_id TEXT NOT NULL,
              principal_id TEXT NOT NULL, category TEXT NOT NULL, content TEXT NOT NULL,
              created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
              FOREIGN KEY(tenant_id) REFERENCES arc_tenants(tenant_id),
              FOREIGN KEY(application_id) REFERENCES arc_applications(application_id),
              FOREIGN KEY(principal_id) REFERENCES arc_principals(principal_id)
            );
            CREATE INDEX IF NOT EXISTS idx_arc_memory_scope
              ON arc_scoped_memories(tenant_id,application_id,principal_id,category,created_at);
            CREATE TABLE IF NOT EXISTS arc_memory_grants(
              grant_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
              source_application_id TEXT NOT NULL, destination_application_id TEXT NOT NULL,
              principal_id TEXT NOT NULL, categories_json TEXT NOT NULL, purpose TEXT NOT NULL,
              expires_at INTEGER, grant_version INTEGER NOT NULL DEFAULT 1,
              revoked_at INTEGER, created_at INTEGER NOT NULL,
              FOREIGN KEY(tenant_id) REFERENCES arc_tenants(tenant_id),
              FOREIGN KEY(source_application_id) REFERENCES arc_applications(application_id),
              FOREIGN KEY(destination_application_id) REFERENCES arc_applications(application_id),
              FOREIGN KEY(principal_id) REFERENCES arc_principals(principal_id)
            );
            CREATE INDEX IF NOT EXISTS idx_arc_memory_grants_scope
              ON arc_memory_grants(tenant_id,source_application_id,destination_application_id,principal_id);
            CREATE TABLE IF NOT EXISTS arc_scoped_tasks(
              task_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,application_id TEXT NOT NULL,
              principal_id TEXT NOT NULL,agent_id TEXT NOT NULL,required_capabilities_json TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
              payload_json TEXT NOT NULL,result_json TEXT,worker_id TEXT,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
              FOREIGN KEY(tenant_id) REFERENCES arc_tenants(tenant_id),
              FOREIGN KEY(application_id) REFERENCES arc_applications(application_id),
              FOREIGN KEY(principal_id) REFERENCES arc_principals(principal_id)
            );
            CREATE INDEX IF NOT EXISTS idx_arc_scoped_tasks_claim
              ON arc_scoped_tasks(tenant_id,application_id,status,created_at);
            CREATE TRIGGER IF NOT EXISTS arc_credentials_scope_insert
            BEFORE INSERT ON arc_credentials
            WHEN NOT EXISTS (SELECT 1 FROM arc_applications a
              WHERE a.application_id=NEW.application_id AND a.tenant_id=NEW.tenant_id)
            BEGIN SELECT RAISE(ABORT,'credential tenant/application mismatch'); END;
            CREATE TRIGGER IF NOT EXISTS arc_memories_scope_insert
            BEFORE INSERT ON arc_scoped_memories
            WHEN NOT EXISTS (SELECT 1 FROM arc_applications a
              WHERE a.application_id=NEW.application_id AND a.tenant_id=NEW.tenant_id)
            BEGIN SELECT RAISE(ABORT,'memory tenant/application mismatch'); END;
            CREATE TRIGGER IF NOT EXISTS arc_tasks_scope_insert
            BEFORE INSERT ON arc_scoped_tasks
            WHEN NOT EXISTS (SELECT 1 FROM arc_applications a
              WHERE a.application_id=NEW.application_id AND a.tenant_id=NEW.tenant_id)
            BEGIN SELECT RAISE(ABORT,'task tenant/application mismatch'); END;
            CREATE TRIGGER IF NOT EXISTS arc_memory_grants_scope_insert
            BEFORE INSERT ON arc_memory_grants
            WHEN NOT EXISTS (SELECT 1 FROM arc_applications a
              WHERE a.application_id=NEW.source_application_id AND a.tenant_id=NEW.tenant_id)
              OR NOT EXISTS (SELECT 1 FROM arc_applications a
              WHERE a.application_id=NEW.destination_application_id AND a.tenant_id=NEW.tenant_id)
            BEGIN SELECT RAISE(ABORT,'memory grant tenant/application mismatch'); END;
            """)
            db.execute("INSERT OR IGNORE INTO arc_schema_migrations(version,applied_at) VALUES(1,?)",(int(time.time()),))
            db.commit()

    def create_tenant(self, name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Tenant name is required")
        tenant_id = "ten_" + uuid.uuid4().hex
        with self._session() as db:
            db.execute("INSERT INTO arc_tenants VALUES(?,?,?,?)",
                       (tenant_id, name.strip()[:160], "active", int(time.time())))
            db.commit()
        return tenant_id

    def create_application(self, tenant_id: str, name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Application name is required")
        app_id = "app_" + uuid.uuid4().hex
        with self._session() as db:
            tenant = db.execute("SELECT status FROM arc_tenants WHERE tenant_id=?", (tenant_id,)).fetchone()
            if not tenant or tenant["status"] != "active":
                raise AuthorizationError("Active tenant required")
            db.execute("INSERT INTO arc_applications VALUES(?,?,?,?,?,?)",
                       (app_id, tenant_id, name.strip()[:160], "active", 1, int(time.time())))
            db.commit()
        return app_id

    def issue_credential(self, tenant_id: str, application_id: str, principal_id: str,
                         capabilities: Iterable[str], ttl_seconds: int = 86400) -> str:
        caps = sorted(set(capabilities))
        if not caps or any(not isinstance(x, str) or not x or len(x) > 100 for x in caps):
            raise ValueError("At least one valid capability is required")
        if not 60 <= ttl_seconds <= 31536000:
            raise ValueError("Credential TTL must be between one minute and one year")
        credential_id = "cred_" + uuid.uuid4().hex
        secret = secrets.token_urlsafe(32)
        token = credential_id + "." + secret
        digest = hashlib.sha256(secret.encode()).hexdigest()
        now = int(time.time())
        with self._session() as db:
            tenant = db.execute("SELECT status FROM arc_tenants WHERE tenant_id=?", (tenant_id,)).fetchone()
            app = db.execute("SELECT tenant_id,status FROM arc_applications WHERE application_id=?",
                             (application_id,)).fetchone()
            if not tenant or tenant["status"] != "active" or not app or app["status"] != "active" or app["tenant_id"] != tenant_id:
                raise AuthorizationError("Tenant/application binding is invalid")
            db.execute("INSERT OR IGNORE INTO arc_principals VALUES(?,?,?)",
                       (principal_id, "active", now))
            principal = db.execute("SELECT status FROM arc_principals WHERE principal_id=?",
                                   (principal_id,)).fetchone()
            if principal["status"] != "active":
                raise AuthorizationError("Principal is not active")
            db.execute("""INSERT INTO arc_credentials
              (credential_id,secret_hash,tenant_id,application_id,principal_id,capabilities_json,expires_at,created_at)
              VALUES(?,?,?,?,?,?,?,?)""",
              (credential_id,digest,tenant_id,application_id,principal_id,
               __import__("json").dumps(caps),now+ttl_seconds,now))
            db.commit()
        return token

    def authenticate(self, token: str) -> RequestIdentity:
        import json
        if not isinstance(token, str) or "." not in token:
            raise AuthorizationError("Invalid application credential")
        credential_id, secret = token.split(".", 1)
        if not credential_id.startswith("cred_") or not secret:
            raise AuthorizationError("Invalid application credential")
        digest = hashlib.sha256(secret.encode()).hexdigest()
        now = int(time.time())
        with self._session() as db:
            row = db.execute("""SELECT c.*,t.status tenant_status,a.status app_status,
              a.policy_version,p.status principal_status
              FROM arc_credentials c
              JOIN arc_tenants t ON t.tenant_id=c.tenant_id
              JOIN arc_applications a ON a.application_id=c.application_id AND a.tenant_id=c.tenant_id
              JOIN arc_principals p ON p.principal_id=c.principal_id
              WHERE c.credential_id=?""", (credential_id,)).fetchone()
            if not row or not hmac.compare_digest(row["secret_hash"], digest):
                raise AuthorizationError("Invalid application credential")
            if row["revoked_at"] is not None or (row["expires_at"] is not None and row["expires_at"] <= now):
                raise AuthorizationError("Application credential expired or revoked")
            if any(row[key] != "active" for key in ("tenant_status","app_status","principal_status")):
                raise AuthorizationError("Tenant, application, or principal is inactive")
            db.execute("UPDATE arc_credentials SET last_used_at=? WHERE credential_id=?", (now,credential_id))
            db.commit()
            return RequestIdentity(credential_id,row["tenant_id"],row["application_id"],
                                   row["principal_id"],frozenset(json.loads(row["capabilities_json"])),
                                   int(row["policy_version"]))


    def identity_for_execution(self, credential_id: str, tenant_id: str,
                               application_id: str, principal_id: str,
                               policy_version: int) -> RequestIdentity:
        """Resolve the exact submitting principal from a live execution, never from payload fields."""
        if not all(isinstance(value, str) and value for value in
                   (credential_id, tenant_id, application_id, principal_id)):
            raise AuthorizationError("Execution identity is incomplete")
        now = int(time.time())
        with self._session() as db:
            row = db.execute("""SELECT c.capabilities_json,c.expires_at,c.revoked_at,
                a.policy_version,a.status AS app_status,t.status AS tenant_status,
                p.status AS principal_status
                FROM arc_credentials c
                JOIN arc_applications a ON a.tenant_id=c.tenant_id
                  AND a.application_id=c.application_id
                JOIN arc_tenants t ON t.tenant_id=c.tenant_id
                JOIN arc_principals p ON p.principal_id=c.principal_id
                WHERE c.credential_id=? AND c.tenant_id=?
                  AND c.application_id=? AND c.principal_id=?""",
                (credential_id, tenant_id, application_id, principal_id)).fetchone()
        if (row is None or row["revoked_at"] is not None
                or (row["expires_at"] is not None and row["expires_at"] <= now)
                or row["tenant_status"] != "active"
                or row["app_status"] != "active"
                or row["principal_status"] != "active"
                or row["policy_version"] != policy_version):
            raise AuthorizationError("Submitting application identity is no longer authorized")
        import json
        return RequestIdentity(
            credential_id, tenant_id, application_id, principal_id,
            frozenset(json.loads(row["capabilities_json"])), int(row["policy_version"]),
        )

    def create_scoped_task(self, identity: RequestIdentity, agent_id: str,
                           required_capabilities: Iterable[str], payload: dict) -> str:
        import json
        if not isinstance(agent_id,str) or not agent_id or not isinstance(payload,dict):
            raise ValueError("Invalid scoped task")
        required=sorted(set(required_capabilities))
        self.require(identity,"agent."+agent_id+".dispatch")
        if any(cap not in identity.capabilities for cap in required):
            raise AuthorizationError("Task capability is not granted to this application principal")
        task_id="task_"+uuid.uuid4().hex
        now=int(time.time())
        with self._session() as db:
            db.execute("""INSERT INTO arc_scoped_tasks
              (task_id,tenant_id,application_id,principal_id,agent_id,required_capabilities_json,
               status,payload_json,created_at,updated_at)
              VALUES(?,?,?,?,?,?, 'queued',?,?,?)""",
              (task_id,identity.tenant_id,identity.application_id,identity.principal_id,
               agent_id,json.dumps(required),json.dumps(payload,ensure_ascii=False),now,now))
        return task_id

    def claim_scoped_task(self, identity: RequestIdentity, task_id: str, worker_id: str) -> dict:
        import json
        if not worker_id or len(worker_id)>128:
            raise ValueError("Invalid worker identity")
        with self._session() as db:
            row=db.execute("""SELECT * FROM arc_scoped_tasks WHERE task_id=? AND tenant_id=?
              AND application_id=? AND status='queued'""",
              (task_id,identity.tenant_id,identity.application_id)).fetchone()
            if not row:
                raise AuthorizationError("Queued task not found in this application scope")
            required=json.loads(row["required_capabilities_json"])
            self.require(identity,"agent.tasks.claim")
            self.require(identity,"agent."+row["agent_id"]+".dispatch")
            if any(cap not in identity.capabilities for cap in required):
                raise AuthorizationError("Worker no longer has required task capabilities")
            changed=db.execute("""UPDATE arc_scoped_tasks SET status='running',worker_id=?,updated_at=?
              WHERE task_id=? AND status='queued'""",(worker_id,int(time.time()),task_id))
            if changed.rowcount!=1:
                raise AuthorizationError("Task was claimed concurrently")
            return {"task_id":task_id,"agent_id":row["agent_id"],"required_capabilities":required,
                    "payload":json.loads(row["payload_json"]),"tenant_id":identity.tenant_id,
                    "application_id":identity.application_id,"principal_id":row["principal_id"],
                    "worker_id":worker_id,"status":"running"}

    def complete_scoped_task(self, identity: RequestIdentity, task_id: str,
                             worker_id: str, result: dict, status: str="succeeded") -> bool:
        import json
        if status not in {"succeeded","failed","cancelled"} or not isinstance(result,dict):
            raise ValueError("Invalid task completion")
        self.require(identity,"agent.tasks.complete")
        with self._session() as db:
            row=db.execute(
                "SELECT agent_id,required_capabilities_json FROM arc_scoped_tasks "
                "WHERE task_id=? AND tenant_id=? AND application_id=? "
                "AND worker_id=? AND status='running'",
                (task_id,identity.tenant_id,identity.application_id,worker_id)
            ).fetchone()
            if not row:
                return False
            required=json.loads(row["required_capabilities_json"])
            self.require(identity,"agent."+row["agent_id"]+".dispatch")
            if any(cap not in identity.capabilities for cap in required):
                raise AuthorizationError("Worker no longer has required task capabilities")
            cur=db.execute(
                "UPDATE arc_scoped_tasks SET status=?,result_json=?,updated_at=? "
                "WHERE task_id=? AND tenant_id=? AND application_id=? "
                "AND worker_id=? AND status='running'",
                (status,json.dumps(result,ensure_ascii=False),int(time.time()),task_id,
                 identity.tenant_id,identity.application_id,worker_id)
            )
            return cur.rowcount==1

    def get_scoped_task(self, identity: RequestIdentity, task_id: str) -> dict | None:
        import json
        with self._session() as db:
            row=db.execute("""SELECT * FROM arc_scoped_tasks WHERE task_id=? AND tenant_id=?
              AND application_id=? AND principal_id=?""",
              (task_id,identity.tenant_id,identity.application_id,identity.principal_id)).fetchone()
        if not row:
            return None
        return {"task_id":row["task_id"],"agent_id":row["agent_id"],"status":row["status"],
                "required_capabilities":json.loads(row["required_capabilities_json"]),
                "result":json.loads(row["result_json"]) if row["result_json"] else None}

    def revoke_credential(self, credential_id: str) -> bool:
        now = int(time.time())
        with self._session() as db:
            credential = db.execute(
                "SELECT tenant_id,application_id,principal_id FROM arc_credentials WHERE credential_id=? AND revoked_at IS NULL",
                (credential_id,),
            ).fetchone()
            if credential is None:
                return False
            cur = db.execute(
                "UPDATE arc_credentials SET revoked_at=? WHERE credential_id=? AND revoked_at IS NULL",
                (now, credential_id),
            )
            if cur.rowcount != 1:
                return False
            # Grants are owned by the source principal within the source app.
            # Keep them only while that principal has another live credential
            # in the same app; credentials in unrelated apps do not keep them alive.
            remaining = db.execute(
                """SELECT capabilities_json FROM arc_credentials
                   WHERE tenant_id=? AND application_id=? AND principal_id=?
                     AND revoked_at IS NULL AND expires_at>?""",
                (credential["tenant_id"], credential["application_id"],
                 credential["principal_id"], now),
            ).fetchall()
            # A credential without the sharing capability cannot keep another
            # credential's SPARK grants alive.
            has_live_share_authority = False
            for row in remaining:
                try:
                    if "spark.memory.share" in json.loads(row["capabilities_json"]):
                        has_live_share_authority = True
                        break
                except (TypeError, json.JSONDecodeError):
                    continue
            if not has_live_share_authority:
                db.execute(
                    """UPDATE arc_memory_grants
                       SET revoked_at=?, grant_version=grant_version+1
                       WHERE tenant_id=? AND source_application_id=? AND principal_id=?
                         AND revoked_at IS NULL""",
                    (now, credential["tenant_id"], credential["application_id"],
                     credential["principal_id"]),
                )
            db.commit()
            return True

    @staticmethod
    def require(identity: RequestIdentity, capability: str):
        if capability not in identity.capabilities:
            raise AuthorizationError("Required capability is not granted")

    def save_memory(self, identity: RequestIdentity, content: str, category: str = "preference") -> str:
        self.require(identity, "spark.memory.write")
        if category not in {"preference","project","learning","sensitive"}:
            raise ValueError("Unsupported memory category")
        if category == "sensitive":
            self.require(identity, "spark.memory.sensitive")
        if not isinstance(content,str) or not content.strip() or len(content)>20000:
            raise ValueError("Memory content is invalid")
        memory_id="mem_"+uuid.uuid4().hex
        now=int(time.time())
        with self._session() as db:
            db.execute("""INSERT INTO arc_scoped_memories
              VALUES(?,?,?,?,?,?,?,?)""",
              (memory_id,identity.tenant_id,identity.application_id,identity.principal_id,
               category,content.strip(),now,now))
            db.commit()
        return memory_id

    def list_memories(self, identity: RequestIdentity, limit: int = 100) -> list[dict]:
        self.require(identity, "spark.memory.read")
        with self._session() as db:
            rows=db.execute("""SELECT memory_id,category,content,created_at,updated_at
              FROM arc_scoped_memories WHERE tenant_id=? AND application_id=? AND principal_id=?
              ORDER BY created_at DESC LIMIT ?""",
              (identity.tenant_id,identity.application_id,identity.principal_id,max(1,min(limit,200)))).fetchall()
        return [dict(row) for row in rows if row["category"] != "sensitive" or "spark.memory.sensitive" in identity.capabilities]

    def share_memory(self, identity: RequestIdentity, destination_application_id: str,
                     categories: Iterable[str], purpose: str, ttl_seconds: int = 86400) -> str:
        self.require(identity, "spark.memory.share")
        allowed={"preference","project","learning"}
        selected=sorted(set(categories))
        if not selected or not set(selected).issubset(allowed) or not purpose.strip():
            raise ValueError("Memory sharing requires allowed categories and a purpose")
        grant_id="mgrant_"+uuid.uuid4().hex
        now=int(time.time())
        with self._session() as db:
            dest=db.execute("SELECT tenant_id,status FROM arc_applications WHERE application_id=?",
                            (destination_application_id,)).fetchone()
            if not dest or dest["tenant_id"] != identity.tenant_id or dest["status"] != "active":
                raise AuthorizationError("Destination must be an active app in the same tenant")
            db.execute("""INSERT INTO arc_memory_grants
              (grant_id,tenant_id,source_application_id,destination_application_id,principal_id,
               categories_json,purpose,expires_at,created_at)
              VALUES(?,?,?,?,?,?,?,?,?)""",
              (grant_id,identity.tenant_id,identity.application_id,destination_application_id,
               identity.principal_id,__import__("json").dumps(selected),purpose.strip()[:500],
               now+max(60,min(ttl_seconds,31536000)),now))
            db.commit()
        return grant_id

    def revoke_memory_share(self, identity: RequestIdentity, grant_id: str) -> bool:
        self.require(identity, "spark.memory.share")
        with self._session() as db:
            cur=db.execute("""UPDATE arc_memory_grants SET revoked_at=?,grant_version=grant_version+1
              WHERE grant_id=? AND tenant_id=? AND source_application_id=? AND principal_id=? AND revoked_at IS NULL""",
              (int(time.time()),grant_id,identity.tenant_id,identity.application_id,identity.principal_id))
            db.commit()
            return cur.rowcount == 1

    def shared_memories(self, identity: RequestIdentity, source_application_id: str) -> list[dict]:
        self.require(identity, "spark.memory.read_shared")
        import json
        now=int(time.time())
        with self._session() as db:
            grants=db.execute("""SELECT * FROM arc_memory_grants WHERE tenant_id=?
              AND source_application_id=? AND destination_application_id=? AND principal_id=?
              AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>?)""",
              (identity.tenant_id,source_application_id,identity.application_id,identity.principal_id,now)).fetchall()
            output=[]
            for grant in grants:
                cats=json.loads(grant["categories_json"])
                marks=",".join("?" for _ in cats)
                rows=db.execute(f"""SELECT memory_id,category,content,created_at,updated_at
                  FROM arc_scoped_memories WHERE tenant_id=? AND application_id=? AND principal_id=?
                  AND category IN ({marks}) ORDER BY created_at DESC""",
                  (identity.tenant_id,source_application_id,identity.principal_id,*cats)).fetchall()
                output.extend(dict(row) for row in rows)
        return output
