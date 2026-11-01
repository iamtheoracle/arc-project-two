"""Tenant-isolated Oracle Arc platform control plane.

This is a metadata and execution-control plane, not an arbitrary code loader.
Agent versions are immutable manifests; runtimes must be separately trusted and
must re-authorize the live identity immediately before every consequential action.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from typing import Any

from .tenant_identity import RequestIdentity


_ID = re.compile(r"^[a-z][a-z0-9._-]{1,63}$")
_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$")


@dataclass(frozen=True)
class AgentVersion:
    tenant_id: str
    application_id: str
    agent_id: str
    version: str
    manifest: dict[str, Any]
    manifest_digest: str


@dataclass(frozen=True)
class Execution:
    execution_id: str
    tenant_id: str
    application_id: str
    principal_id: str
    agent_id: str
    agent_version: str
    model_provider: str
    model_id: str
    status: str
    attempt: int
    max_attempts: int
    input_json: str
    output_json: str | None
    error_code: str | None
    lease_expires_at: int | None


class PlatformControlPlane:
    """SQLite-backed tenant/application registry, quota ledger and task lifecycle."""

    def __init__(self, database_path: str):
        self.database_path = database_path
        with self._session() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS arc_agent_versions(
              tenant_id TEXT NOT NULL, application_id TEXT NOT NULL,
              agent_id TEXT NOT NULL, version TEXT NOT NULL,
              manifest_json TEXT NOT NULL, manifest_digest TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('active','disabled')),
              created_at INTEGER NOT NULL,
              PRIMARY KEY(tenant_id,application_id,agent_id,version)
            );
            CREATE TABLE IF NOT EXISTS arc_model_routes(
              tenant_id TEXT NOT NULL, application_id TEXT NOT NULL,
              route_id TEXT NOT NULL, provider_id TEXT NOT NULL, model_id TEXT NOT NULL,
              data_classifications_json TEXT NOT NULL, regions_json TEXT NOT NULL,
              enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
              PRIMARY KEY(tenant_id,application_id,route_id)
            );
            CREATE TABLE IF NOT EXISTS arc_app_quotas(
              tenant_id TEXT NOT NULL, application_id TEXT NOT NULL,
              window_seconds INTEGER NOT NULL, max_executions INTEGER NOT NULL,
              max_concurrent INTEGER NOT NULL, max_input_bytes INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              PRIMARY KEY(tenant_id,application_id)
            );
            CREATE TABLE IF NOT EXISTS arc_usage_ledger(
              usage_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
              application_id TEXT NOT NULL, execution_id TEXT NOT NULL,
              metric TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity >= 0),
              recorded_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS arc_usage_window
              ON arc_usage_ledger(tenant_id,application_id,recorded_at);
            CREATE TABLE IF NOT EXISTS arc_executions(
              execution_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
              application_id TEXT NOT NULL, principal_id TEXT NOT NULL,
              agent_id TEXT NOT NULL, agent_version TEXT NOT NULL,
              model_provider TEXT NOT NULL, model_id TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN
                ('queued','running','succeeded','failed','cancelled','dead_letter')),
              attempt INTEGER NOT NULL, max_attempts INTEGER NOT NULL,
              input_json TEXT NOT NULL, output_json TEXT, error_code TEXT,
              created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
              lease_owner TEXT, lease_expires_at INTEGER,
              idempotency_key TEXT,
              request_digest TEXT,
              UNIQUE(tenant_id,application_id,idempotency_key)
            );
            CREATE INDEX IF NOT EXISTS arc_execution_claim
              ON arc_executions(status,created_at);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(arc_executions)")}
            if "request_digest" not in columns:
                db.execute("ALTER TABLE arc_executions ADD COLUMN request_digest TEXT")
            db.commit()

    def _connect(self):
        db = sqlite3.connect(self.database_path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
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
    def _require(identity: RequestIdentity, capability: str) -> None:
        if capability not in identity.capabilities:
            raise PermissionError("Required platform capability is not granted")

    @staticmethod
    def _valid_id(value: str, label: str) -> str:
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise ValueError(f"{label} must be a normalized identifier")
        return value

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def register_agent(self, identity: RequestIdentity, agent_id: str,
                       version: str, manifest: dict[str, Any]) -> AgentVersion:
        self._require(identity, "agent.register")
        self._valid_id(agent_id, "Agent ID")
        if not isinstance(version, str) or not _VERSION.fullmatch(version):
            raise ValueError("Agent version must use semantic versioning")
        if not isinstance(manifest, dict):
            raise ValueError("Agent manifest must be an object")
        required = {"display_name", "description", "required_capabilities",
                    "allowed_tools", "model_routes", "runtime"}
        if set(manifest) != required:
            raise ValueError("Agent manifest fields do not match the platform contract")
        for key in ("display_name", "description", "runtime"):
            if not isinstance(manifest[key], str) or not manifest[key].strip() or len(manifest[key]) > 500:
                raise ValueError(f"Invalid agent manifest field: {key}")
        trusted_runtimes = {x.strip() for x in os.environ.get(
            "ORACLE_ARC_TRUSTED_RUNTIME_IDS", "oracle-arc-agent-v1").split(",") if x.strip()}
        if manifest["runtime"] not in trusted_runtimes:
            raise PermissionError("Agent runtime is not in the server-side trusted runtime allowlist")
        caps, tools, routes = (manifest["required_capabilities"],
                               manifest["allowed_tools"], manifest["model_routes"])
        if (not isinstance(caps, list) or not caps or
            any(not isinstance(x, str) or not x.strip() or len(x) > 100 for x in caps) or
            len(set(caps)) != len(caps)):
            raise ValueError("Agent capabilities must be a unique non-empty string list")
        if (not isinstance(tools, list) or
            any(not isinstance(x, str) or not _ID.fullmatch(x) for x in tools) or
            len(set(tools)) != len(tools)):
            raise ValueError("Agent tools must be a unique list of normalized tool IDs")
        if (not isinstance(routes, list) or not routes or
            any(not isinstance(x, str) or not _ID.fullmatch(x) for x in routes) or
            len(set(routes)) != len(routes)):
            raise ValueError("Agent must reference one or more valid model route IDs")
        if not set(caps).issubset(identity.capabilities):
            raise PermissionError("Application identity lacks one or more agent-required capabilities")
        if not set(tools).issubset(identity.capabilities):
            raise PermissionError("Application identity lacks one or more agent tool grants")
        canonical = self._json(manifest)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self._session() as db:
            db.execute("BEGIN IMMEDIATE")
            for route_id in routes:
                route = db.execute("""SELECT 1 FROM arc_model_routes
                    WHERE tenant_id=? AND application_id=? AND route_id=? AND enabled=1""",
                    (identity.tenant_id, identity.application_id, route_id)).fetchone()
                if route is None:
                    raise LookupError("Every agent model route must already exist and be enabled")
            db.execute("""INSERT INTO arc_agent_versions
                VALUES(?,?,?,?,?,?,'active',?)""",
                (identity.tenant_id, identity.application_id, agent_id, version,
                 canonical, digest, int(time.time())))
        return AgentVersion(identity.tenant_id, identity.application_id,
                            agent_id, version, manifest, digest)

    def get_agent(self, identity: RequestIdentity, agent_id: str,
                  version: str | None = None) -> AgentVersion:
        self._require(identity, "agent.read")
        self._valid_id(agent_id, "Agent ID")
        with self._session() as db:
            if version is None:
                row = db.execute("""SELECT * FROM arc_agent_versions
                    WHERE tenant_id=? AND application_id=? AND agent_id=? AND status='active'
                    ORDER BY created_at DESC, version DESC LIMIT 1""",
                    (identity.tenant_id, identity.application_id, agent_id)).fetchone()
            else:
                row = db.execute("""SELECT * FROM arc_agent_versions
                    WHERE tenant_id=? AND application_id=? AND agent_id=? AND version=? AND status='active'""",
                    (identity.tenant_id, identity.application_id, agent_id, version)).fetchone()
        if row is None:
            raise LookupError("Agent version not found")
        manifest = json.loads(row["manifest_json"])
        digest = hashlib.sha256(self._json(manifest).encode("utf-8")).hexdigest()
        if digest != row["manifest_digest"]:
            raise RuntimeError("Stored agent manifest integrity check failed")
        return AgentVersion(row["tenant_id"], row["application_id"], row["agent_id"],
                            row["version"], manifest, digest)

    def disable_agent_version(self, identity: RequestIdentity, agent_id: str, version: str) -> bool:
        self._require(identity, "agent.manage")
        with self._session() as db:
            cur = db.execute("""UPDATE arc_agent_versions SET status='disabled'
                WHERE tenant_id=? AND application_id=? AND agent_id=? AND version=?""",
                (identity.tenant_id, identity.application_id, agent_id, version))
            return cur.rowcount == 1

    def configure_model_route(self, identity: RequestIdentity, route_id: str,
                              provider_id: str, model_id: str,
                              classifications: list[str], regions: list[str]) -> None:
        self._require(identity, "model.route.manage")
        self._valid_id(route_id, "Route ID")
        self._valid_id(provider_id, "Provider ID")
        if provider_id not in {"ollama", "openrouter", "groq", "gemini"}:
            raise ValueError("Provider is not part of the registered Oracle Arc provider set")
        if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 256:
            raise ValueError("Model ID is required and must be at most 256 characters")
        allowed = {"public", "internal", "private", "sensitive", "restricted"}
        if (not isinstance(classifications, list) or not classifications or
            any(x not in allowed for x in classifications) or len(set(classifications)) != len(classifications)):
            raise ValueError("Invalid route data classifications")
        if (not isinstance(regions, list) or not regions or
            any(not isinstance(x, str) or not x.strip() or len(x) > 64 for x in regions) or
            len(set(regions)) != len(regions)):
            raise ValueError("At least one unique execution region is required")
        with self._session() as db:
            db.execute("""INSERT INTO arc_model_routes VALUES(?,?,?,?,?,?,?,1)
                ON CONFLICT(tenant_id,application_id,route_id) DO UPDATE SET
                provider_id=excluded.provider_id, model_id=excluded.model_id,
                data_classifications_json=excluded.data_classifications_json,
                regions_json=excluded.regions_json, enabled=1""",
                (identity.tenant_id, identity.application_id, route_id, provider_id,
                 model_id, self._json(classifications), self._json(regions)))

    def resolve_model_route(self, identity: RequestIdentity, route_id: str,
                            classification: str, region: str) -> dict[str, str]:
        self._require(identity, "model.route.use")
        with self._session() as db:
            row = db.execute("""SELECT * FROM arc_model_routes
                WHERE tenant_id=? AND application_id=? AND route_id=? AND enabled=1""",
                (identity.tenant_id, identity.application_id, route_id)).fetchone()
        if row is None:
            raise LookupError("Model route not found")
        if classification not in json.loads(row["data_classifications_json"]):
            raise PermissionError("Model route is not approved for this data classification")
        if region not in json.loads(row["regions_json"]):
            raise PermissionError("Model route is not approved for this execution region")
        return {"provider_id": row["provider_id"], "model_id": row["model_id"]}

    def set_quota(self, identity: RequestIdentity, *, window_seconds: int,
                  max_executions: int, max_concurrent: int,
                  max_input_bytes: int) -> None:
        self._require(identity, "quota.manage")
        bounds = ((window_seconds, 1, 86400), (max_executions, 1, 1_000_000),
                  (max_concurrent, 1, 10_000), (max_input_bytes, 1, 10_000_000))
        if any(not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi
               for v, lo, hi in bounds):
            raise ValueError("Quota values are outside supported bounds")
        with self._session() as db:
            db.execute("""INSERT INTO arc_app_quotas VALUES(?,?,?,?,?, ?,?)
                ON CONFLICT(tenant_id,application_id) DO UPDATE SET
                window_seconds=excluded.window_seconds,
                max_executions=excluded.max_executions,
                max_concurrent=excluded.max_concurrent,
                max_input_bytes=excluded.max_input_bytes, updated_at=excluded.updated_at""",
                (identity.tenant_id, identity.application_id, window_seconds,
                 max_executions, max_concurrent, max_input_bytes, int(time.time())))

    def _route_for_agent(self, db, identity, agent_id, version, route_id):
        agent = db.execute("""SELECT manifest_json,status FROM arc_agent_versions
            WHERE tenant_id=? AND application_id=? AND agent_id=? AND version=?""",
            (identity.tenant_id, identity.application_id, agent_id, version)).fetchone()
        if agent is None or agent["status"] != "active":
            raise LookupError("Active agent version not found")
        manifest = json.loads(agent["manifest_json"])
        if route_id not in manifest["model_routes"]:
            raise PermissionError("Agent manifest does not permit this model route")
        route = db.execute("""SELECT * FROM arc_model_routes
            WHERE tenant_id=? AND application_id=? AND route_id=? AND enabled=1""",
            (identity.tenant_id, identity.application_id, route_id)).fetchone()
        if route is None:
            raise LookupError("Enabled model route not found")
        if not set(manifest["required_capabilities"]).issubset(identity.capabilities):
            raise PermissionError("Application identity lacks agent-required capabilities")
        if not set(manifest["allowed_tools"]).issubset(set(identity.capabilities)):
            raise PermissionError("Application identity lacks one or more agent tool grants")
        return route

    def submit_execution(self, identity: RequestIdentity, agent_id: str, version: str,
                         route_id: str, payload: dict[str, Any],
                         classification: str = "private", region: str = "local",
                         max_attempts: int = 3, idempotency_key: str | None = None) -> str:
        self._require(identity, "agent.execute")
        self._valid_id(agent_id, "Agent ID")
        self._valid_id(route_id, "Route ID")
        if not isinstance(payload, dict):
            raise ValueError("Execution payload must be an object")
        input_json = self._json(payload)
        if len(input_json.encode("utf-8")) > 1_000_000:
            raise ValueError("Execution payload exceeds one megabyte")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        if idempotency_key is not None and (not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128):
            raise ValueError("Invalid idempotency key")
        now = int(time.time())
        with self._session() as db:
            db.execute("BEGIN IMMEDIATE")
            route = self._route_for_agent(db, identity, agent_id, version, route_id)
            if classification not in json.loads(route["data_classifications_json"]):
                raise PermissionError("Model route is not approved for this data classification")
            if region not in json.loads(route["regions_json"]):
                raise PermissionError("Model route is not approved for this execution region")
            request_digest = hashlib.sha256(input_json.encode("utf-8")).hexdigest()
            if idempotency_key is not None:
                existing = db.execute("""SELECT execution_id,request_digest FROM arc_executions
                    WHERE tenant_id=? AND application_id=? AND idempotency_key=?""",
                    (identity.tenant_id, identity.application_id, idempotency_key)).fetchone()
                if existing is not None:
                    if existing["request_digest"] != request_digest:
                        raise ValueError("Idempotency key was already used with a different request payload")
                    return existing["execution_id"]
            quota = db.execute("""SELECT * FROM arc_app_quotas
                WHERE tenant_id=? AND application_id=?""",
                (identity.tenant_id, identity.application_id)).fetchone()
            if quota is None:
                raise PermissionError("Application execution quota must be configured before workloads are queued")
            if quota:
                if len(input_json.encode("utf-8")) > quota["max_input_bytes"]:
                    raise PermissionError("Application input-size quota exceeded")
                window_start = now - quota["window_seconds"]
                count = db.execute("""SELECT COUNT(*) FROM arc_executions
                    WHERE tenant_id=? AND application_id=? AND created_at>=?""",
                    (identity.tenant_id, identity.application_id, window_start)).fetchone()[0]
                active = db.execute("""SELECT COUNT(*) FROM arc_executions
                    WHERE tenant_id=? AND application_id=? AND status IN ('queued','running')""",
                    (identity.tenant_id, identity.application_id)).fetchone()[0]
                if count >= quota["max_executions"] or active >= quota["max_concurrent"]:
                    raise PermissionError("Application execution quota exceeded")
            execution_id = "exe_" + uuid.uuid4().hex
            try:
                db.execute("""INSERT INTO arc_executions
                    (execution_id,tenant_id,application_id,principal_id,agent_id,agent_version,
                     model_provider,model_id,status,attempt,max_attempts,input_json,created_at,
                     updated_at,idempotency_key,request_digest)
                    VALUES(?,?,?,?,?,?,?,?, 'queued',0,?,?,?, ?,?,?)""",
                    (execution_id, identity.tenant_id, identity.application_id, identity.principal_id,
                     agent_id, version, route["provider_id"], route["model_id"], max_attempts,
                     input_json, now, now, idempotency_key, request_digest))
            except sqlite3.IntegrityError:
                if idempotency_key is None:
                    raise
                existing = db.execute("""SELECT execution_id,request_digest FROM arc_executions
                    WHERE tenant_id=? AND application_id=? AND idempotency_key=?""",
                    (identity.tenant_id, identity.application_id, idempotency_key)).fetchone()
                if existing is None:
                    raise
                if existing["request_digest"] != request_digest:
                    raise ValueError("Idempotency key was already used with a different request payload")
                return existing["execution_id"]
        return execution_id

    @staticmethod
    def _execution(row) -> Execution:
        return Execution(**{key: row[key] for key in Execution.__dataclass_fields__})

    def claim_execution(self, worker_id: str, lease_seconds: int = 60) -> Execution | None:
        if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id) > 128:
            raise ValueError("Worker ID is required")
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 5 <= lease_seconds <= 900:
            raise ValueError("Lease must be between 5 and 900 seconds")
        now = int(time.time())
        with self._session() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT * FROM arc_executions
                WHERE status='queued' ORDER BY created_at,execution_id LIMIT 1""").fetchone()
            if row is None:
                return None
            cur = db.execute("""UPDATE arc_executions SET status='running',attempt=attempt+1,
                lease_owner=?,lease_expires_at=?,updated_at=?
                WHERE execution_id=? AND status='queued'""",
                (worker_id, now + lease_seconds, now, row["execution_id"]))
            if cur.rowcount != 1:
                return None
            claimed = db.execute("SELECT * FROM arc_executions WHERE execution_id=?",
                                 (row["execution_id"],)).fetchone()
            return self._execution(claimed)

    def heartbeat_execution(self, execution_id: str, worker_id: str,
                            lease_seconds: int = 60) -> bool:
        if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id) > 128:
            raise ValueError("Worker ID is required")
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 5 <= lease_seconds <= 900:
            raise ValueError("Lease must be between 5 and 900 seconds")
        now = int(time.time())
        with self._session() as db:
            cur = db.execute("""UPDATE arc_executions SET lease_expires_at=?,updated_at=?
                WHERE execution_id=? AND status='running' AND lease_owner=? AND lease_expires_at>?""",
                (now + lease_seconds, now, execution_id, worker_id, now))
            return cur.rowcount == 1

    def complete_execution(self, execution_id: str, worker_id: str,
                           output: dict[str, Any]) -> bool:
        if not isinstance(output, dict):
            raise ValueError("Execution output must be an object")
        now = int(time.time())
        with self._session() as db:
            cur = db.execute("""UPDATE arc_executions SET status='succeeded',output_json=?,
                updated_at=?,lease_owner=NULL,lease_expires_at=NULL
                WHERE execution_id=? AND status='running' AND lease_owner=?
                AND lease_expires_at>?""",
                (self._json(output), now, execution_id, worker_id, now))
            return cur.rowcount == 1

    def fail_execution(self, execution_id: str, worker_id: str,
                       error_code: str, retryable: bool = True) -> bool:
        if not isinstance(error_code, str) or not re.fullmatch(r"[a-z0-9_.-]{1,80}", error_code):
            raise ValueError("Error code must be a normalized non-sensitive code")
        now = int(time.time())
        with self._session() as db:
            row = db.execute("""SELECT attempt,max_attempts FROM arc_executions
                WHERE execution_id=? AND status='running' AND lease_owner=?
                AND lease_expires_at>?""", (execution_id, worker_id, now)).fetchone()
            if row is None:
                return False
            status = "queued" if retryable and row["attempt"] < row["max_attempts"] else (
                "dead_letter" if retryable else "failed")
            db.execute("""UPDATE arc_executions SET status=?,error_code=?,updated_at=?,
                lease_owner=NULL,lease_expires_at=NULL WHERE execution_id=?""",
                (status, error_code, now, execution_id))
            return True

    def recover_expired_leases(self) -> dict[str, int]:
        now = int(time.time())
        with self._session() as db:
            db.execute("BEGIN IMMEDIATE")
            expired = db.execute("""SELECT execution_id,attempt,max_attempts FROM arc_executions
                WHERE status='running' AND lease_expires_at<=?""", (now,)).fetchall()
            counts = {"requeued": 0, "dead_letter": 0}
            for row in expired:
                status = "queued" if row["attempt"] < row["max_attempts"] else "dead_letter"
                db.execute("""UPDATE arc_executions SET status=?,error_code='worker_lease_expired',
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=?
                    WHERE execution_id=? AND status='running' AND lease_expires_at<=?""",
                    (status, now, row["execution_id"], now))
                counts["requeued" if status == "queued" else "dead_letter"] += 1
            return counts

    def get_execution(self, identity: RequestIdentity, execution_id: str) -> Execution:
        self._require(identity, "agent.execution.read")
        with self._session() as db:
            row = db.execute("""SELECT * FROM arc_executions
                WHERE execution_id=? AND tenant_id=? AND application_id=? AND principal_id=?""",
                (execution_id, identity.tenant_id, identity.application_id, identity.principal_id)).fetchone()
        if row is None:
            raise LookupError("Execution not found")
        return self._execution(row)

    def cancel_execution(self, identity: RequestIdentity, execution_id: str) -> bool:
        self._require(identity, "agent.execution.cancel")
        now = int(time.time())
        with self._session() as db:
            cur = db.execute("""UPDATE arc_executions SET status='cancelled',updated_at=?
                lease_owner=NULL,lease_expires_at=NULL,error_code='cancelled_by_principal'
                WHERE execution_id=? AND tenant_id=? AND application_id=? AND principal_id=?
                AND status IN ('queued','running')""",
                (now, execution_id, identity.tenant_id, identity.application_id, identity.principal_id))
            return cur.rowcount == 1

    def record_usage(self, identity: RequestIdentity, execution_id: str,
                     metric: str, quantity: int) -> None:
        self._require(identity, "usage.write")
        if not isinstance(metric, str) or not _ID.fullmatch(metric):
            raise ValueError("Invalid usage metric")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 0 <= quantity <= 2**63 - 1:
            raise ValueError("Usage quantity must be a non-negative integer")
        with self._session() as db:
            owner = db.execute("""SELECT 1 FROM arc_executions
                WHERE execution_id=? AND tenant_id=? AND application_id=?""",
                (execution_id, identity.tenant_id, identity.application_id)).fetchone()
            if owner is None:
                raise LookupError("Execution not found")
            db.execute("""INSERT INTO arc_usage_ledger
                VALUES(?,?,?,?,?, ?,?)""",
                ("use_" + uuid.uuid4().hex, identity.tenant_id, identity.application_id,
                 execution_id, metric, quantity, int(time.time())))

    def usage_summary(self, identity: RequestIdentity, since: int) -> dict[str, int]:
        self._require(identity, "usage.read")
        if not isinstance(since, int) or since < 0:
            raise ValueError("Usage start time must be a Unix timestamp")
        with self._session() as db:
            rows = db.execute("""SELECT metric,SUM(quantity) AS total FROM arc_usage_ledger
                WHERE tenant_id=? AND application_id=? AND recorded_at>=?
                GROUP BY metric""", (identity.tenant_id, identity.application_id, since)).fetchall()
        return {row["metric"]: row["total"] for row in rows}
