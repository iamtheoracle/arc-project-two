"""CONCIERGE workflow runtime with explicit approval, durable events and safe recovery.

A provider timeout is not proof that an external action failed. Ambiguous outcomes are
recorded as reconciliation_required and are never automatically retried.
"""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable


class ConciergeError(RuntimeError):
    pass


def _fingerprint(action: dict[str, Any]) -> str:
    canonical = json.dumps(action, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class ConciergeWorkflowStore:
    def __init__(self, database_path: str):
        self.path = database_path
        with self._session() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS concierge_workflows(
              workflow_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,application_id TEXT NOT NULL,
              principal_id TEXT NOT NULL,action_json TEXT NOT NULL,action_fingerprint TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('planned','awaiting_confirmation','approved','executing','succeeded','failed','cancelled')),
              expires_at INTEGER NOT NULL,provider_receipt_json TEXT,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(concierge_workflows)")}
            if "provider_outcome" not in columns:
                db.execute("ALTER TABLE concierge_workflows ADD COLUMN provider_outcome TEXT NOT NULL DEFAULT 'not_started'")
            if "provider_error_code" not in columns:
                db.execute("ALTER TABLE concierge_workflows ADD COLUMN provider_error_code TEXT")
            db.execute("""CREATE TABLE IF NOT EXISTS concierge_workflow_events(
              event_id INTEGER PRIMARY KEY AUTOINCREMENT, workflow_id TEXT NOT NULL,
              tenant_id TEXT NOT NULL, application_id TEXT NOT NULL, principal_id TEXT NOT NULL,
              event_type TEXT NOT NULL, status TEXT NOT NULL, details_json TEXT NOT NULL,
              created_at INTEGER NOT NULL)""")
            db.execute("""CREATE INDEX IF NOT EXISTS idx_concierge_scope
              ON concierge_workflows(tenant_id,application_id,principal_id,status)""")
            db.execute("""CREATE INDEX IF NOT EXISTS idx_concierge_events_scope
              ON concierge_workflow_events(tenant_id,application_id,principal_id,workflow_id,event_id)""")
            db.commit()

    @contextmanager
    def _session(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _event(db, identity, workflow_id: str, event_type: str, status: str,
               details: dict[str, Any] | None = None) -> None:
        db.execute("""INSERT INTO concierge_workflow_events
          (workflow_id,tenant_id,application_id,principal_id,event_type,status,details_json,created_at)
          VALUES(?,?,?,?,?,?,?,?)""",
          (workflow_id, identity.tenant_id, identity.application_id, identity.principal_id,
           event_type, status, json.dumps(details or {}, sort_keys=True), int(time.time())))

    def plan(self, identity, action: dict[str, Any], ttl_seconds: int = 900) -> dict:
        if "concierge.workflow.plan" not in set(getattr(identity, "capabilities", ())):
            raise ConciergeError("CONCIERGE workflow capability is not granted")
        required = {"kind", "provider", "parameters", "consequential"}
        if not isinstance(action, dict) or not required.issubset(action):
            raise ConciergeError("Action plan is incomplete")
        if action["consequential"] is not True:
            raise ConciergeError("Use the research/planning path for non-consequential tasks")
        if not isinstance(action["parameters"], dict) or not action["kind"] or not action["provider"]:
            raise ConciergeError("Invalid action plan")
        workflow_id = "cw_" + uuid.uuid4().hex
        now = int(time.time())
        payload = json.dumps(action, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        fp = _fingerprint(action)
        expires_at = now + max(60, min(ttl_seconds, 3600))
        with self._session() as db:
            db.execute("""INSERT INTO concierge_workflows
              (workflow_id,tenant_id,application_id,principal_id,action_json,action_fingerprint,
               status,expires_at,provider_receipt_json,created_at,updated_at,provider_outcome)
              VALUES(?,?,?,?,?,?, 'awaiting_confirmation', ?,NULL,?,?, 'not_started')""",
              (workflow_id, identity.tenant_id, identity.application_id, identity.principal_id,
               payload, fp, expires_at, now, now))
            self._event(db, identity, workflow_id, "workflow.planned", "awaiting_confirmation")
        return {"workflow_id": workflow_id, "status": "awaiting_confirmation",
                "action_fingerprint": fp, "expires_at": expires_at,
                "confirmation_required": True, "execution_performed": False}

    def get(self, identity, workflow_id: str) -> dict:
        if "concierge.workflow.read" not in set(getattr(identity, "capabilities", ())):
            raise ConciergeError("CONCIERGE workflow read capability is not granted")
        with self._session() as db:
            row = db.execute("""SELECT * FROM concierge_workflows WHERE workflow_id=?
              AND tenant_id=? AND application_id=? AND principal_id=?""",
              (workflow_id, identity.tenant_id, identity.application_id, identity.principal_id)).fetchone()
            if row is None:
                raise ConciergeError("Workflow not found")
            events = db.execute("""SELECT event_id,event_type,status,details_json,created_at
              FROM concierge_workflow_events WHERE workflow_id=? AND tenant_id=?
              AND application_id=? AND principal_id=? ORDER BY event_id""",
              (workflow_id, identity.tenant_id, identity.application_id, identity.principal_id)).fetchall()
        return {
            "workflow_id": row["workflow_id"], "status": row["status"],
            "action": json.loads(row["action_json"]),
            "action_fingerprint": row["action_fingerprint"],
            "expires_at": row["expires_at"], "provider_outcome": row["provider_outcome"],
            "provider_error_code": row["provider_error_code"],
            "provider_receipt": json.loads(row["provider_receipt_json"]) if row["provider_receipt_json"] else None,
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "events": [{"event_id": e["event_id"], "event_type": e["event_type"],
                        "status": e["status"], "details": json.loads(e["details_json"]),
                        "created_at": e["created_at"]} for e in events],
            "retry_allowed": row["provider_outcome"] == "not_started",
            "reconciliation_required": row["provider_outcome"] == "unknown",
        }

    def cancel(self, identity, workflow_id: str) -> dict:
        if "concierge.workflow.cancel" not in set(getattr(identity, "capabilities", ())):
            raise ConciergeError("CONCIERGE workflow cancellation capability is not granted")
        with self._session() as db:
            row = db.execute("""SELECT status FROM concierge_workflows WHERE workflow_id=?
              AND tenant_id=? AND application_id=? AND principal_id=?""",
              (workflow_id, identity.tenant_id, identity.application_id, identity.principal_id)).fetchone()
            if row is None:
                raise ConciergeError("Workflow not found")
            if row["status"] != "awaiting_confirmation":
                raise ConciergeError("Only workflows awaiting confirmation can be cancelled; executing actions require provider reconciliation")
            now = int(time.time())
            changed = db.execute("""UPDATE concierge_workflows SET status='cancelled',
              updated_at=? WHERE workflow_id=? AND status='awaiting_confirmation'""",
              (now, workflow_id))
            if changed.rowcount != 1:
                raise ConciergeError("Workflow state changed before cancellation")
            self._event(db, identity, workflow_id, "workflow.cancelled", "cancelled")
        return {"workflow_id": workflow_id, "status": "cancelled", "execution_performed": False}

    def confirm_and_execute(self, identity, workflow_id: str, confirmed_fingerprint: str,
                            executor: Callable[[dict[str, Any], str], dict[str, Any]]) -> dict:
        if "concierge.action.execute" not in set(getattr(identity, "capabilities", ())):
            raise ConciergeError("CONCIERGE action-confirmation capability is not granted")
        with self._session() as db:
            row = db.execute("""SELECT * FROM concierge_workflows WHERE workflow_id=? AND tenant_id=?
              AND application_id=? AND principal_id=?""",
              (workflow_id, identity.tenant_id, identity.application_id, identity.principal_id)).fetchone()
            if not row:
                raise ConciergeError("Workflow not found")
            if row["status"] != "awaiting_confirmation" or row["expires_at"] <= int(time.time()):
                raise ConciergeError("Workflow is not awaiting valid confirmation")
            if not __import__("hmac").compare_digest(row["action_fingerprint"], confirmed_fingerprint):
                raise ConciergeError("Confirmation does not match the exact planned action")
            action = json.loads(row["action_json"])
            if _fingerprint(action) != row["action_fingerprint"]:
                raise ConciergeError("Stored action integrity check failed")
            now = int(time.time())
            claimed = db.execute("""UPDATE concierge_workflows SET status='executing',
              provider_outcome='pending',provider_error_code=NULL,updated_at=?
              WHERE workflow_id=? AND status='awaiting_confirmation'""", (now, workflow_id))
            if claimed.rowcount != 1:
                raise ConciergeError("Workflow was already claimed")
            self._event(db, identity, workflow_id, "provider.execution.started", "executing",
                        {"idempotency_key": workflow_id})
        # workflow_id is the stable provider idempotency key. Adapters must pass it
        # through to providers that support idempotent writes.
        try:
            receipt = executor(action, workflow_id)
            if not isinstance(receipt, dict) or not receipt.get("provider_receipt_id"):
                raise ConciergeError("Provider did not return a verifiable completion receipt")
            if receipt.get("status") in {"rejected", "declined", "failed"}:
                with self._session() as db:
                    db.execute("""UPDATE concierge_workflows SET status='failed',
                      provider_outcome='rejected',provider_receipt_json=?,updated_at=?
                      WHERE workflow_id=? AND status='executing'""",
                      (json.dumps(receipt, sort_keys=True), int(time.time()), workflow_id))
                    self._event(db, identity, workflow_id, "provider.execution.rejected", "failed",
                                {"provider_receipt_id": str(receipt["provider_receipt_id"])[:160]})
                return {"workflow_id": workflow_id, "status": "failed",
                        "provider_outcome": "rejected", "provider_receipt": receipt}
            if receipt.get("status") not in {"confirmed", "completed"}:
                raise ConciergeError("Provider did not return a verifiable completion receipt")
            with self._session() as db:
                db.execute("""UPDATE concierge_workflows SET status='succeeded',
                  provider_outcome='confirmed',provider_receipt_json=?,updated_at=?
                  WHERE workflow_id=? AND status='executing'""",
                  (json.dumps(receipt, sort_keys=True), int(time.time()), workflow_id))
                self._event(db, identity, workflow_id, "provider.execution.confirmed", "succeeded",
                            {"provider_receipt_id": str(receipt["provider_receipt_id"])[:160]})
            return {"workflow_id": workflow_id, "status": "succeeded",
                    "provider_outcome": "confirmed", "provider_receipt": receipt}
        except Exception as exc:
            # A timeout, malformed response, or lost connection can happen after the
            # provider committed the action. Never label this as a definite failure
            # and never automatically retry it.
            error_code = re.sub(r"[^a-z0-9_.-]", "_", type(exc).__name__.lower())[:80] or "provider_error"
            with self._session() as db:
                db.execute("""UPDATE concierge_workflows SET status='failed',
                  provider_outcome='unknown',provider_error_code=?,updated_at=?
                  WHERE workflow_id=? AND status='executing'""",
                  (error_code, int(time.time()), workflow_id))
                self._event(db, identity, workflow_id, "provider.execution.outcome_unknown", "failed",
                            {"error_code": error_code, "reconciliation_required": True})
            if isinstance(exc, ConciergeError):
                raise
            raise ConciergeError("Provider outcome is unknown; reconcile with the provider before any retry") from exc
