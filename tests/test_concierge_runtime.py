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
