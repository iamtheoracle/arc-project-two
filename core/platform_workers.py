"""Independently authenticated, application-bound Oracle Arc workers.

Worker credentials are random, stored only as SHA-256 verifiers, revocable and
bound to one tenant/application plus an explicit set of approved runtime IDs.
This service leases only work in that scope and revalidates worker state on
every operation. It does not load developer-supplied code.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
import uuid
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkerIdentity:
    worker_id: str
    tenant_id: str
    application_id: str
    runtime_ids: tuple[str, ...]
    expires_at: int


class WorkerService:
    def __init__(self, database_path: str):
        self.database_path = str(database_path)
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._db() as db:
            db.execute("""
              CREATE TABLE IF NOT EXISTS arc_workers(
                worker_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                application_id TEXT NOT NULL, principal_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE, runtime_ids_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('active','revoked')),
                created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                revoked_at INTEGER
              )
            """)
            db.execute("""CREATE INDEX IF NOT EXISTS arc_workers_scope
              ON arc_workers(tenant_id,application_id,status)""")

    def _db(self):
        db = sqlite3.connect(self.database_path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        return db

    @staticmethod
    def _runtime_ids(runtime_ids):
        if (not isinstance(runtime_ids, list) or not runtime_ids or len(runtime_ids) > 20
                or any(not isinstance(x, str) or not x.strip() or len(x) > 128 for x in runtime_ids)
                or len(set(runtime_ids)) != len(runtime_ids)):
            raise ValueError("Provide 1–20 unique approved runtime identifiers")
        configured = os.environ.get("ORACLE_ARC_TRUSTED_RUNTIME_IDS", "oracle-arc-agent-v1")
        trusted = {item.strip() for item in configured.split(",") if item.strip()}
        if not set(runtime_ids).issubset(trusted):
            raise PermissionError("Runtime is not in the server-side trusted runtime allowlist")
        return sorted(runtime_ids)

    def register(self, identity, runtime_ids: list[str], ttl_seconds: int = 86400) -> dict:
        if "worker.register" not in identity.capabilities:
            raise PermissionError("worker.register capability is required")
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or not 300 <= ttl_seconds <= 31_536_000:
            raise ValueError("Worker credential lifetime must be 5 minutes to 1 year")
        runtimes = self._runtime_ids(runtime_ids)
        now = int(time.time())
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            # Runtime execution remains server-allowlisted; manifests cannot install code.
            approved = set()
            manifests = db.execute("""SELECT manifest_json FROM arc_agent_versions
              WHERE tenant_id=? AND application_id=? AND status='active'""",
              (identity.tenant_id, identity.application_id)).fetchall()
            for row in manifests:
                try:
                    value = json.loads(row["manifest_json"]).get("runtime")
                    if isinstance(value, str):
                        approved.add(value)
                except (ValueError, TypeError):
                    continue
            if not set(runtimes).issubset(approved):
                raise PermissionError("Worker may only host runtime IDs used by active registered agent versions")
            worker_id = "wrk_" + uuid.uuid4().hex
            secret = secrets.token_urlsafe(48)
            token = "arcw1." + worker_id + "." + secret
            expires_at = now + ttl_seconds
            db.execute("""INSERT INTO arc_workers
              (worker_id,tenant_id,application_id,principal_id,token_hash,runtime_ids_json,
               status,created_at,expires_at)
              VALUES(?,?,?,?,?,?,'active',?,?)""",
              (worker_id, identity.tenant_id, identity.application_id, identity.principal_id,
               hashlib.sha256(token.encode()).hexdigest(), json.dumps(runtimes), now, expires_at))
            db.commit()
            return {"worker_id": worker_id, "credential": token, "shown_once": True,
                    "expires_at": expires_at, "runtime_ids": runtimes}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def authenticate(self, token: str) -> WorkerIdentity:
        if not isinstance(token, str) or len(token) > 512:
            raise PermissionError("Invalid worker credential")
        parts = token.split(".", 2)
        if len(parts) != 3 or parts[0] != "arcw1" or not parts[1].startswith("wrk_"):
            raise PermissionError("Invalid worker credential")
        db = self._db()
        try:
            row = db.execute("SELECT * FROM arc_workers WHERE worker_id=?",
                             (parts[1],)).fetchone()
        finally:
            db.close()
        if row is None or row["status"] != "active" or row["revoked_at"] is not None:
            raise PermissionError("Worker credential is revoked or unavailable")
        if row["expires_at"] <= int(time.time()):
            raise PermissionError("Worker credential has expired")
        if not secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(), row["token_hash"]):
            raise PermissionError("Invalid worker credential")
        return WorkerIdentity(row["worker_id"], row["tenant_id"], row["application_id"],
                              tuple(json.loads(row["runtime_ids_json"])), row["expires_at"])

    def _reauthorize(self, worker: WorkerIdentity) -> None:
        current = self.authenticate_from_identity(worker)
        if current != worker:
            raise PermissionError("Worker identity is stale or no longer authorized")

    def authenticate_from_identity(self, worker: WorkerIdentity) -> WorkerIdentity:
        db = self._db()
        try:
            row = db.execute("""SELECT w.*,t.status AS tenant_status,a.status AS app_status
              FROM arc_workers w
              JOIN arc_tenants t ON t.tenant_id=w.tenant_id
              JOIN arc_applications a ON a.tenant_id=w.tenant_id AND a.application_id=w.application_id
              WHERE w.worker_id=? AND w.tenant_id=? AND w.application_id=?
                AND w.status='active' AND w.revoked_at IS NULL""",
              (worker.worker_id, worker.tenant_id, worker.application_id)).fetchone()
        finally:
            db.close()
        if (row is None or row["expires_at"] <= int(time.time())
                or row["tenant_status"] != "active" or row["app_status"] != "active"):
            raise PermissionError("Worker identity is revoked, expired or disabled")
        return WorkerIdentity(row["worker_id"], row["tenant_id"], row["application_id"],
                              tuple(json.loads(row["runtime_ids_json"])), row["expires_at"])

    def revoke(self, identity, worker_id: str) -> bool:
        if "worker.manage" not in identity.capabilities:
            raise PermissionError("worker.manage capability is required")
        db = self._db()
        try:
            cur = db.execute("""UPDATE arc_workers SET status='revoked',revoked_at=?
              WHERE worker_id=? AND tenant_id=? AND application_id=? AND status='active'""",
              (int(time.time()), worker_id, identity.tenant_id, identity.application_id))
            db.commit()
            return cur.rowcount == 1
        finally:
            db.close()

    def claim(self, worker: WorkerIdentity, lease_seconds: int = 60):
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 5 <= lease_seconds <= 900:
            raise ValueError("Lease must be between 5 and 900 seconds")
        self._reauthorize(worker)
        now = int(time.time())
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("""SELECT e.* FROM arc_executions e
              JOIN arc_agent_versions a ON a.tenant_id=e.tenant_id
                AND a.application_id=e.application_id AND a.agent_id=e.agent_id
                AND a.version=e.agent_version AND a.status='active'
              WHERE e.tenant_id=? AND e.application_id=? AND e.status='queued'
              ORDER BY e.created_at,e.execution_id""",
              (worker.tenant_id, worker.application_id)).fetchall()
            selected = None
            for row in rows:
                manifest = json.loads(db.execute("""SELECT manifest_json FROM arc_agent_versions
                  WHERE tenant_id=? AND application_id=? AND agent_id=? AND version=?""",
                  (row["tenant_id"], row["application_id"], row["agent_id"], row["agent_version"])).fetchone()[0])
                if manifest.get("runtime") in worker.runtime_ids:
                    selected = row
                    break
            if selected is None:
                return None
            cur = db.execute("""UPDATE arc_executions SET status='running',attempt=attempt+1,
              lease_owner=?,lease_expires_at=?,updated_at=?
              WHERE execution_id=? AND status='queued'""",
              (worker.worker_id, now + lease_seconds, now, selected["execution_id"]))
            if cur.rowcount != 1:
                return None
            claimed = db.execute("SELECT * FROM arc_executions WHERE execution_id=?",
                                 (selected["execution_id"],)).fetchone()
            return {key: claimed[key] for key in claimed.keys()}
        finally:
            db.commit()
            db.close()

    def execution_manifest(self, worker: WorkerIdentity, execution_id: str) -> dict:
        """Return only the active manifest attached to this worker's live leased task."""
        self._reauthorize(worker)
        db = self._db()
        try:
            row = db.execute("""SELECT a.manifest_json FROM arc_executions e
              JOIN arc_agent_versions a ON a.tenant_id=e.tenant_id
                AND a.application_id=e.application_id AND a.agent_id=e.agent_id
                AND a.version=e.agent_version
              WHERE e.execution_id=? AND e.tenant_id=? AND e.application_id=?
                AND e.status='running' AND e.lease_owner=? AND e.lease_expires_at>?
                AND a.status='active'""",
              (execution_id, worker.tenant_id, worker.application_id,
               worker.worker_id, int(time.time()))).fetchone()
            if row is None:
                raise PermissionError("No active execution lease is owned by this worker")
            return json.loads(row["manifest_json"])
        finally:
            db.close()

    def heartbeat(self, worker: WorkerIdentity, execution_id: str, lease_seconds: int = 60) -> bool:
        self._reauthorize(worker)
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 5 <= lease_seconds <= 900:
            raise ValueError("Lease must be between 5 and 900 seconds")
        now = int(time.time())
        db = self._db()
        try:
            cur = db.execute("""UPDATE arc_executions SET lease_expires_at=?,updated_at=?
              WHERE execution_id=? AND tenant_id=? AND application_id=? AND status='running'
              AND lease_owner=? AND lease_expires_at>?""",
              (now + lease_seconds, now, execution_id, worker.tenant_id,
               worker.application_id, worker.worker_id, now))
            db.commit()
            return cur.rowcount == 1
        finally:
            db.close()

    def complete(self, worker: WorkerIdentity, execution_id: str, output: dict) -> bool:
        self._reauthorize(worker)
        if not isinstance(output, dict):
            raise ValueError("Worker output must be an object")
        encoded = json.dumps(output, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 1_000_000:
            raise ValueError("Worker output exceeds one megabyte")
        now = int(time.time())
        db = self._db()
        try:
            cur = db.execute("""UPDATE arc_executions SET status='succeeded',output_json=?,
              updated_at=?,lease_owner=NULL,lease_expires_at=NULL
              WHERE execution_id=? AND tenant_id=? AND application_id=? AND status='running'
              AND lease_owner=? AND lease_expires_at>?""",
              (encoded, now, execution_id, worker.tenant_id, worker.application_id,
               worker.worker_id, now))
            db.commit()
            return cur.rowcount == 1
        finally:
            db.close()

    def record_usage(self, worker: WorkerIdentity, execution_id: str,
                     event_id: str, metric: str, quantity: int) -> bool:
        self._reauthorize(worker)
        import re
        if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", event_id):
            raise ValueError("Usage event ID must be a stable non-sensitive identifier")
        if not isinstance(metric, str) or not re.fullmatch(r"[a-z][a-z0-9._-]{1,63}", metric):
            raise ValueError("Invalid usage metric")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 0 <= quantity <= 2**63 - 1:
            raise ValueError("Usage quantity must be a non-negative integer")
        now = int(time.time())
        usage_id = "use_" + hashlib.sha256(
            (worker.worker_id + ":" + execution_id + ":" + event_id).encode()).hexdigest()
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            execution = db.execute("""SELECT 1 FROM arc_executions
              WHERE execution_id=? AND tenant_id=? AND application_id=? AND status='running'
              AND lease_owner=? AND lease_expires_at>?""",
              (execution_id, worker.tenant_id, worker.application_id, worker.worker_id, now)).fetchone()
            if execution is None:
                raise PermissionError("Usage can only be recorded against the worker's active execution lease")
            existing = db.execute("SELECT metric,quantity FROM arc_usage_ledger WHERE usage_id=?",
                                  (usage_id,)).fetchone()
            if existing is not None:
                if existing["metric"] != metric or existing["quantity"] != quantity:
                    raise ValueError("Usage event ID was reused with different values")
                return False
            db.execute("""INSERT INTO arc_usage_ledger
              (usage_id,tenant_id,application_id,execution_id,metric,quantity,recorded_at)
              VALUES(?,?,?,?,?,?,?)""",
              (usage_id, worker.tenant_id, worker.application_id, execution_id, metric, quantity, now))
            db.commit()
            return True
        finally:
            db.close()

    def fail(self, worker: WorkerIdentity, execution_id: str,
             error_code: str, retryable: bool = True) -> bool:
        self._reauthorize(worker)
        import re
        if not isinstance(error_code, str) or not re.fullmatch(r"[a-z0-9_.-]{1,80}", error_code):
            raise ValueError("Error code must be a normalized non-sensitive code")
        now = int(time.time())
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT attempt,max_attempts FROM arc_executions
              WHERE execution_id=? AND tenant_id=? AND application_id=? AND status='running'
              AND lease_owner=? AND lease_expires_at>?""",
              (execution_id, worker.tenant_id, worker.application_id, worker.worker_id, now)).fetchone()
            if row is None:
                return False
            status = "queued" if retryable and row["attempt"] < row["max_attempts"] else (
                "dead_letter" if retryable else "failed")
            db.execute("""UPDATE arc_executions SET status=?,error_code=?,updated_at=?,
              lease_owner=NULL,lease_expires_at=NULL WHERE execution_id=?""",
              (status, error_code, now, execution_id))
            db.commit()
            return True
        finally:
            db.close()
