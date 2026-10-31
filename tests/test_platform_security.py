import pytest

from core.tenant_security import (
    TenantSecurityStore, AuthorizationError, RequestIdentity,
)
from core.concierge_runtime import ConciergeWorkflowStore, ConciergeError
from core.privacy_aware_gateway import (
    PrivacyAwareModelGateway, InferencePolicy, ProviderPolicyError,
)


def test_application_credentials_are_bound_to_tenant_app_and_principal(tmp_path):
    store=TenantSecurityStore(tmp_path/"arc.sqlite3")
    tenant=store.create_tenant("MY REALM")
    app_a=store.create_application(tenant,"UNIBUD")
    app_b=store.create_application(tenant,"WAYWARD")
    token=store.issue_credential(tenant,app_a,"user-1",["spark.memory.read","spark.memory.write"])
    identity=store.authenticate(token)
    assert identity.tenant_id==tenant
    assert identity.application_id==app_a
    assert identity.principal_id=="user-1"
    assert "spark.memory.write" in identity.capabilities
    assert app_b != identity.application_id
    assert "." in token
    assert store.revoke_credential(identity.credential_id)
    with pytest.raises(AuthorizationError):
        store.authenticate(token)


def test_spark_memory_isolation_and_explicit_revocable_cross_app_grant(tmp_path):
    store=TenantSecurityStore(tmp_path/"arc.sqlite3")
    tenant=store.create_tenant("Tenant")
    app_a=store.create_application(tenant,"UNIBUD")
    app_b=store.create_application(tenant,"WAYWARD")
    app_c=store.create_application(tenant,"SOULYNC")
    source_token=store.issue_credential(
        tenant,app_a,"principal-1",
        ["spark.memory.read","spark.memory.write","spark.memory.share"])
    dest_token=store.issue_credential(
        tenant,app_b,"principal-1",["spark.memory.read_shared"])
    unrelated_token=store.issue_credential(
        tenant,app_c,"principal-1",["spark.memory.read_shared"])
    source=store.authenticate(source_token)
    destination=store.authenticate(dest_token)
    unrelated=store.authenticate(unrelated_token)
    memory_id=store.save_memory(source,"Current university project","project")
    assert store.list_memories(destination)==[]
    assert store.shared_memories(destination,app_a)==[]
    grant=store.share_memory(source,app_b,["project"],"Continue a project across apps")
    shared=store.shared_memories(destination,app_a)
    assert [item["memory_id"] for item in shared]==[memory_id]
    assert store.shared_memories(unrelated,app_a)==[]
    assert store.revoke_memory_share(source,grant)
    assert store.shared_memories(destination,app_a)==[]


def test_spark_sensitive_memory_requires_separate_capability(tmp_path):
    store=TenantSecurityStore(tmp_path/"arc.sqlite3")
    tenant=store.create_tenant("Tenant")
    app=store.create_application(tenant,"App")
    token=store.issue_credential(tenant,app,"user",["spark.memory.write"])
    identity=store.authenticate(token)
    with pytest.raises(AuthorizationError):
        store.save_memory(identity,"sensitive content","sensitive")


def test_credentials_cannot_bind_application_to_another_tenant(tmp_path):
    store=TenantSecurityStore(tmp_path/"arc.sqlite3")
    tenant_a=store.create_tenant("A")
    tenant_b=store.create_tenant("B")
    app_b=store.create_application(tenant_b,"App B")
    with pytest.raises(AuthorizationError):
        store.issue_credential(tenant_a,app_b,"user",["spark.memory.read"])


def test_concierge_requires_exact_confirmation_and_provider_receipt(tmp_path):
    identity=RequestIdentity("cred","tenant","app","user",frozenset({"concierge.execute"}),1)
    store=ConciergeWorkflowStore(str(tmp_path/"arc.sqlite3"))
    action={"kind":"calendar.create_event","provider":"calendar-test",
            "parameters":{"title":"Study group"},"consequential":True}
    planned=store.plan(identity,action)
    assert planned["status"]=="awaiting_confirmation"
    assert planned["execution_performed"] is False
    with pytest.raises(ConciergeError):
        store.confirm_and_execute(identity,planned["workflow_id"],"0"*64,
                                   lambda *_:{"status":"completed","provider_receipt_id":"receipt"})
    result=store.confirm_and_execute(
        identity,planned["workflow_id"],planned["action_fingerprint"],
        lambda *_:{"status":"confirmed","provider_receipt_id":"provider-confirmed-123"})
    assert result["status"]=="succeeded"
    assert result["provider_receipt"]["provider_receipt_id"]=="provider-confirmed-123"


def test_concierge_rejects_cross_application_workflow_access(tmp_path):
    store=ConciergeWorkflowStore(str(tmp_path/"arc.sqlite3"))
    source=RequestIdentity("c1","tenant","app-a","user",frozenset(),1)
    other=RequestIdentity("c2","tenant","app-b","user",frozenset(),1)
    action={"kind":"booking.create","provider":"provider","parameters":{"slot":"10:00"},"consequential":True}
    planned=store.plan(source,action)
    with pytest.raises(ConciergeError):
        store.confirm_and_execute(other,planned["workflow_id"],planned["action_fingerprint"],
                                  lambda *_:{"status":"confirmed","provider_receipt_id":"x"})


def test_provider_gateway_denies_remote_egress_by_default():
    class FakeLocal:
        def provider_manifest(self):
            return {"execution_location":"local"}
        def chat(self,**kwargs):
            return {"message":{"content":"local answer"}}
    gateway=PrivacyAwareModelGateway(local_gateway=FakeLocal(),remote_providers={})
    policy=InferencePolicy("t","a","p")
    result=gateway.chat(policy,"local-model",[{"role":"user","content":"hello"}])
    assert result.provider_id=="ollama"
    assert result.remote_egress is False


def test_provider_gateway_requires_allowlist_for_remote_ollama():
    class FakeRemoteOllama:
        def provider_manifest(self):
            return {"execution_location":"remote"}
        def chat(self,**kwargs):
            return "answer"
    gateway=PrivacyAwareModelGateway(local_gateway=FakeRemoteOllama(),remote_providers={})
    denied=InferencePolicy("t","a","p")
    with pytest.raises(ProviderPolicyError):
        gateway.chat(denied,"model",[{"role":"user","content":"private"}])
    allowed=InferencePolicy("t","a","p",allow_remote=True,
                            allowed_remote_providers=frozenset({"ollama"}))
    result=gateway.chat(allowed,"model",[{"role":"user","content":"approved"}])
    assert result.remote_egress is True


def test_remote_provider_needs_request_level_policy_and_data_must_be_exportable():
    class FakeRemote:
        config=type("Config",(),{"provider_id":"remote-x"})()
        configured=True
        def chat(self,payload):
            return "remote answer"
    gateway=PrivacyAwareModelGateway(local_gateway=object(),
                                     remote_providers={"remote-x":(FakeRemote(),"eu")})
    denied=InferencePolicy("t","a","p",allow_remote=True,
                           allowed_remote_providers=frozenset({"remote-x"}),
                           data_classification="sensitive")
    with pytest.raises(ProviderPolicyError):
        gateway.chat(denied,"model",[{"role":"user","content":"private"}],
                     preferred_provider="remote-x")
    allowed=InferencePolicy("t","a","p",allow_remote=True,
                            allowed_remote_providers=frozenset({"remote-x"}),
                            allowed_regions=frozenset({"eu"}),required_region="eu")
    result=gateway.chat(allowed,"model",[{"role":"user","content":"public"}],
                        preferred_provider="remote-x")
    assert result.remote_egress is True


def test_agent_task_queue_is_scoped_and_worker_reauthorizes_capabilities(tmp_path):
    store=TenantSecurityStore(tmp_path/"arc.sqlite3")
    tenant=store.create_tenant("Tenant")
    app_a=store.create_application(tenant,"A")
    app_b=store.create_application(tenant,"B")
    caps=["agent.oracle.dispatch","reasoning"]
    a=store.authenticate(store.issue_credential(tenant,app_a,"p1",caps))
    b=store.authenticate(store.issue_credential(tenant,app_b,"p1",caps))
    worker=store.authenticate(store.issue_credential(
        tenant,app_a,"service-worker",["agent.tasks.claim","agent.oracle.dispatch","reasoning"]))
    task_id=store.create_scoped_task(a,"oracle",["reasoning"],{"prompt":"analyze"})
    assert store.get_scoped_task(b,task_id) is None
    with pytest.raises(AuthorizationError):
        store.claim_scoped_task(b,task_id,"worker-b")
    claimed=store.claim_scoped_task(worker,task_id,"worker-a")
    assert claimed["status"]=="running"
    assert claimed["principal_id"]=="p1"
    assert claimed["payload"]["prompt"]=="analyze"
    assert store.complete_scoped_task(worker,task_id,"worker-a",{"answer":"done"})
    assert store.get_scoped_task(a,task_id)["status"]=="succeeded"


def test_agent_task_requires_dispatch_and_each_requested_capability(tmp_path):
    store=TenantSecurityStore(tmp_path/"arc.sqlite3")
    tenant=store.create_tenant("Tenant")
    app=store.create_application(tenant,"App")
    identity=store.authenticate(store.issue_credential(
        tenant,app,"p1",["agent.oracle.dispatch"]))
    with pytest.raises(AuthorizationError):
        store.create_scoped_task(identity,"oracle",["reasoning"],{"prompt":"no grant"})
