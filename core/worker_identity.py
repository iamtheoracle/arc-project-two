"""Independent, revocable worker credentials for Oracle Arc execution workers.

Worker secrets are one-time-issued and hashed at rest. A worker is permanently
bound to one tenant/application and a fixed capability set.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, hmac, secrets, sqlite3, time, uuid
from contextlib import contextmanager
from pathlib import Path


@dataclass(frozen=True)
class WorkerIdentity:
    worker_id: str
    tenant_id: str
    application_id: str
    capabilities: frozenset[str]
    expires_at: int


class WorkerIdentityStore:
    def __init__(self, database_path: str):
        self.path = str(database_path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._session() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS arc_workers(
                worker_id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL UNIQUE,
                tenant_id TEXT NOT NULL, application_id TEXT NOT NULL,
                capabilities_json TEXT NOT NULL, expires_at INTEGER NOT NULL,
                revoked_at INTEGER, created_at INTEGER NOT NULL,
                FOREIGN KEY(tenant_id,application_id)
                  REFERENCES arc_applications(tenant_id,application_id))""")
            db.execute("""CREATE INDEX IF NOT EXISTS arc_workers_scope
                ON arc_workers(tenant_id,application_id,revoked_at)""")

    @contextmanager
    def _session(self):
        db=sqlite3.connect(self.path,timeout=15)
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def issue(self, tenant_id: str, application_id: str,
              capabilities: list[str], ttl_seconds: int=86400) -> tuple[str,str]:
        allowed={"execution.claim","execution.heartbeat","execution.complete","execution.fail","tool.calculate"}
        if not isinstance(capabilities,list) or not capabilities or len(set(capabilities))!=len(capabilities):
            raise ValueError("Worker capabilities must be a unique non-empty list")
        if not set(capabilities).issubset(allowed):
            raise ValueError("Worker capability is not supported")
        if not isinstance(ttl_seconds,int) or isinstance(ttl_seconds,bool) or not 60<=ttl_seconds<=2592000:
            raise ValueError("Worker credential lifetime must be between one minute and 30 days")
        worker_id="wrk_"+uuid.uuid4().hex
        secret=secrets.token_urlsafe(48)
        digest=hashlib.sha256(secret.encode()).hexdigest()
        now=int(time.time())
        with self._session() as db:
            app=db.execute("""SELECT 1 FROM arc_applications
                WHERE tenant_id=? AND application_id=? AND status='active'""",
                (tenant_id,application_id)).fetchone()
            tenant=db.execute("SELECT 1 FROM arc_tenants WHERE tenant_id=? AND status='active'",(tenant_id,)).fetchone()
            if not app or not tenant:
                raise LookupError("Active tenant/application scope not found")
            db.execute("""INSERT INTO arc_workers
                (worker_id,secret_hash,tenant_id,application_id,capabilities_json,expires_at,created_at)
                VALUES(?,?,?,?,?,?,?)""",
                (worker_id,digest,tenant_id,application_id,__import__("json").dumps(sorted(capabilities)),now+ttl_seconds,now))
        return worker_id, worker_id+"."+secret

    def authenticate(self, token: str) -> WorkerIdentity:
        if not isinstance(token,str) or "." not in token:
            raise PermissionError("Worker authentication required")
        worker_id,secret=token.split(".",1)
        digest=hashlib.sha256(secret.encode()).hexdigest()
        with self._session() as db:
            row=db.execute("""SELECT w.*,a.status app_status,t.status tenant_status
                FROM arc_workers w
                JOIN arc_applications a ON a.application_id=w.application_id AND a.tenant_id=w.tenant_id
                JOIN arc_tenants t ON t.tenant_id=w.tenant_id
                WHERE w.worker_id=?""",(worker_id,)).fetchone()
        if not row or not hmac.compare_digest(row["secret_hash"],digest):
            raise PermissionError("Invalid worker credential")
        if row["revoked_at"] is not None or row["expires_at"]<=int(time.time()):
            raise PermissionError("Worker credential is expired or revoked")
        if row["app_status"]!="active" or row["tenant_status"]!="active":
            raise PermissionError("Worker application or tenant is inactive")
        import json
        return WorkerIdentity(row["worker_id"],row["tenant_id"],row["application_id"],
                              frozenset(json.loads(row["capabilities_json"])),row["expires_at"])

    def revoke(self, worker_id: str) -> bool:
        with self._session() as db:
            cur=db.execute("UPDATE arc_workers SET revoked_at=? WHERE worker_id=? AND revoked_at IS NULL",
                           (int(time.time()),worker_id))
            return cur.rowcount==1

    def validate(self, identity: WorkerIdentity, capability: str) -> WorkerIdentity:
        current=self.authenticate # credential is intentionally not retained in identity
        with self._session() as db:
            row=db.execute("""SELECT w.revoked_at,w.expires_at,w.tenant_id,w.application_id,
                w.capabilities_json,a.status app_status,t.status tenant_status
                FROM arc_workers w JOIN arc_applications a ON a.application_id=w.application_id
                AND a.tenant_id=w.tenant_id JOIN arc_tenants t ON t.tenant_id=w.tenant_id
                WHERE w.worker_id=?""",(identity.worker_id,)).fetchone()
        if not row or row["revoked_at"] is not None or row["expires_at"]<=int(time.time()):
            raise PermissionError("Worker identity is expired or revoked")
        if row["tenant_id"]!=identity.tenant_id or row["application_id"]!=identity.application_id:
            raise PermissionError("Worker scope changed")
        if row["app_status"]!="active" or row["tenant_status"]!="active":
            raise PermissionError("Worker scope is inactive")
        import json
        caps=frozenset(json.loads(row["capabilities_json"]))
        if caps!=identity.capabilities or capability not in caps:
            raise PermissionError("Worker capability is absent or has changed")
        return identity
