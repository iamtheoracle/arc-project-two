from types import SimpleNamespace
import pytest
from core.concierge_runtime import ConciergeError, ConciergeWorkflowStore


def identity(*capabilities):
    return SimpleNamespace(tenant_id="tenant-a",application_id="app-a",
                           principal_id="user-a",capabilities=capabilities)


def test_concierge_requires_capability_and_exact_user_confirmation(tmp_path):
    store=ConciergeWorkflowStore(str(tmp_path/"concierge.sqlite3"))
    action={"kind":"booking.create","provider":"test-booking",
            "parameters":{"slot":"slot-123"},"consequential":True}
    with pytest.raises(ConciergeError,match="workflow capability"):
        store.plan(identity(),action)
    plan=store.plan(identity("concierge.workflow.plan"),action)
    with pytest.raises(ConciergeError,match="action-confirmation capability"):
        store.confirm_and_execute(identity("concierge.workflow.plan"),plan["workflow_id"],
                                  plan["action_fingerprint"],lambda a,k: {})
    with pytest.raises(ConciergeError,match="exact planned action"):
        store.confirm_and_execute(identity("concierge.workflow.plan","concierge.action.execute"),
                                  plan["workflow_id"],"0"*64,lambda a,k: {})
    result=store.confirm_and_execute(identity("concierge.workflow.plan","concierge.action.execute"),
        plan["workflow_id"],plan["action_fingerprint"],
        lambda action,key:{"provider_receipt_id":"receipt-1","status":"confirmed"})
    assert result["status"]=="succeeded"
    assert result["provider_receipt"]["provider_receipt_id"]=="receipt-1"


def test_concierge_requires_provider_receipt_and_is_not_silently_successful(tmp_path):
    store=ConciergeWorkflowStore(str(tmp_path/"concierge.sqlite3"))
    action={"kind":"payment.create","provider":"provider",
            "parameters":{"amount":10},"consequential":True}
    plan=store.plan(identity("concierge.workflow.plan"),action)
    with pytest.raises(ConciergeError,match="verifiable completion receipt"):
        store.confirm_and_execute(identity("concierge.workflow.plan","concierge.action.execute"),
            plan["workflow_id"],plan["action_fingerprint"],lambda a,k:{"success":True})


def test_provider_timeout_is_unknown_and_requires_reconciliation_before_retry(tmp_path):
    store = ConciergeWorkflowStore(str(tmp_path / "concierge.sqlite3"))
    who = identity("concierge.workflow.plan", "concierge.action.execute", "concierge.workflow.read")
    action = {"kind": "booking.create", "provider": "provider",
              "parameters": {"slot": "slot-unknown"}, "consequential": True}
    plan = store.plan(who, action)
    with pytest.raises(ConciergeError, match="outcome is unknown"):
        store.confirm_and_execute(who, plan["workflow_id"], plan["action_fingerprint"],
                                  lambda a, key: (_ for _ in ()).throw(TimeoutError()))
    state = store.get(who, plan["workflow_id"])
    assert state["status"] == "failed"
    assert state["provider_outcome"] == "unknown"
    assert state["reconciliation_required"] is True
    assert state["retry_allowed"] is False
    assert [event["event_type"] for event in state["events"]] == [
        "workflow.planned", "provider.execution.started", "provider.execution.outcome_unknown"
    ]


def test_concierge_workflow_history_is_principal_scoped(tmp_path):
    store = ConciergeWorkflowStore(str(tmp_path / "concierge.sqlite3"))
    owner = identity("concierge.workflow.plan", "concierge.workflow.read")
    plan = store.plan(owner, {"kind": "booking.create", "provider": "provider",
                              "parameters": {"slot": "private-slot"}, "consequential": True})
    other = SimpleNamespace(tenant_id="tenant-a", application_id="app-a",
                            principal_id="different-user", capabilities=("concierge.workflow.read",))
    with pytest.raises(ConciergeError, match="Workflow not found"):
        store.get(other, plan["workflow_id"])


def test_concierge_can_cancel_only_before_provider_execution(tmp_path):
    store = ConciergeWorkflowStore(str(tmp_path / "concierge.sqlite3"))
    who = identity("concierge.workflow.plan", "concierge.workflow.cancel", "concierge.workflow.read")
    plan = store.plan(who, {"kind": "booking.create", "provider": "provider",
                            "parameters": {"slot": "slot-cancel"}, "consequential": True})
    cancelled = store.cancel(who, plan["workflow_id"])
    assert cancelled == {"workflow_id": plan["workflow_id"], "status": "cancelled",
                         "execution_performed": False}
    state = store.get(who, plan["workflow_id"])
    assert state["status"] == "cancelled"
    assert [event["event_type"] for event in state["events"]] == [
        "workflow.planned", "workflow.cancelled"
    ]
