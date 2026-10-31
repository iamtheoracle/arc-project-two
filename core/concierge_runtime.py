"""CONCIERGE workflow runtime with explicit approval and provider receipts.

Research/planning can be performed without side effects. Consequential execution requires
a user-bound approval for the exact action fingerprint and an injected trusted executor.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable


class ConciergeError(RuntimeError):
    pass


def _fingerprint(action: dict[str, Any]) -> str:
    canonical=json.dumps(action,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class ConciergeWorkflowStore:
    def __init__(self, database_path: str):
        self.path=database_path
        with self._session() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS concierge_workflows(
              workflow_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,application_id TEXT NOT NULL,
              principal_id TEXT NOT NULL,action_json TEXT NOT NULL,action_fingerprint TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('planned','awaiting_confirmation','approved','executing','succeeded','failed','cancelled')),
              expires_at INTEGER NOT NULL,provider_receipt_json TEXT,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_concierge_scope ON concierge_workflows(tenant_id,application_id,principal_id,status)")
            db.commit()

    @contextmanager
    def _session(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def plan(self, identity, action: dict[str,Any], ttl_seconds: int=900) -> dict:
        if "concierge.workflow" not in set(getattr(identity, "capabilities", ())):
            raise ConciergeError("CONCIERGE workflow capability is not granted")
        required={"kind","provider","parameters","consequential"}
        if not isinstance(action,dict) or not required.issubset(action):
            raise ConciergeError("Action plan is incomplete")
        if action["consequential"] is not True:
            raise ConciergeError("Use the research/planning path for non-consequential tasks")
        if not isinstance(action["parameters"],dict) or not action["kind"] or not action["provider"]:
            raise ConciergeError("Invalid action plan")
        workflow_id="cw_"+uuid.uuid4().hex
        now=int(time.time())
        payload=json.dumps(action,sort_keys=True,separators=(",",":"),ensure_ascii=False)
        fp=_fingerprint(action)
        with self._session() as db:
            db.execute("""INSERT INTO concierge_workflows VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
              (workflow_id,identity.tenant_id,identity.application_id,identity.principal_id,
               payload,fp,"awaiting_confirmation",now+max(60,min(ttl_seconds,3600)),None,now,now))
            db.commit()
        return {"workflow_id":workflow_id,"status":"awaiting_confirmation","action_fingerprint":fp,
                "confirmation_required":True,"execution_performed":False}

    def confirm_and_execute(self, identity, workflow_id: str, confirmed_fingerprint: str,
                            executor: Callable[[dict[str,Any],str],dict[str,Any]]) -> dict:
        if "concierge.action.confirm" not in set(getattr(identity, "capabilities", ())):
            raise ConciergeError("CONCIERGE action-confirmation capability is not granted")
        with self._session() as db:
            db.row_factory=sqlite3.Row
            row=db.execute("""SELECT * FROM concierge_workflows WHERE workflow_id=? AND tenant_id=?
              AND application_id=? AND principal_id=?""",
              (workflow_id,identity.tenant_id,identity.application_id,identity.principal_id)).fetchone()
            if not row:
                raise ConciergeError("Workflow not found")
            if row["status"] != "awaiting_confirmation" or row["expires_at"] <= int(time.time()):
                raise ConciergeError("Workflow is not awaiting valid confirmation")
            if not __import__("hmac").compare_digest(row["action_fingerprint"],confirmed_fingerprint):
                raise ConciergeError("Confirmation does not match the exact planned action")
            action=json.loads(row["action_json"])
            if _fingerprint(action) != row["action_fingerprint"]:
                raise ConciergeError("Stored action integrity check failed")
            claimed=db.execute("UPDATE concierge_workflows SET status='executing',updated_at=? WHERE workflow_id=? AND status='awaiting_confirmation'",
                       (int(time.time()),workflow_id))
            if claimed.rowcount != 1:
                raise ConciergeError("Workflow was already claimed")
            db.commit()
        # Executor must return a provider-confirmed receipt; a bare success boolean is not enough.
        try:
            receipt=executor(action,workflow_id)
            if not isinstance(receipt,dict) or not receipt.get("provider_receipt_id") or receipt.get("status") not in {"confirmed","completed"}:
                raise ConciergeError("Provider did not return a verifiable completion receipt")
            with self._session() as db:
                db.execute("UPDATE concierge_workflows SET status='succeeded',provider_receipt_json=?,updated_at=? WHERE workflow_id=? AND status='executing'",
                           (json.dumps(receipt,sort_keys=True),int(time.time()),workflow_id))
                db.commit()
            return {"workflow_id":workflow_id,"status":"succeeded","provider_receipt":receipt}
        except Exception:
            with self._session() as db:
                db.execute("UPDATE concierge_workflows SET status='failed',updated_at=? WHERE workflow_id=? AND status='executing'",
                           (int(time.time()),workflow_id))
                db.commit()
            raise
