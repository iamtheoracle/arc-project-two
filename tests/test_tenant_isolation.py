import pytest
from core.tenant_identity import TenantIdentityStore
from core.tenant_store import TenantStore


def test_credentials_resolve_server_side_scope_and_revoke(tmp_path):
    path=str(tmp_path/"tenant.sqlite3")
    identities=TenantIdentityStore(path)
    issued=identities.provision("Tenant A","UNIBUD","principal-a",
        ["conversation.write","conversation.read","memory.write"])
    resolved=identities.authenticate(issued["secret"])
    assert resolved.tenant_id==issued["tenant_id"]
    assert resolved.application_id==issued["application_id"]
    assert resolved.principal_id=="principal-a"
    assert set(resolved.capabilities)=={"conversation.write","conversation.read","memory.write"}
    assert identities.revoke(issued["credential_id"]) is True
    with pytest.raises(PermissionError):
        identities.authenticate(issued["secret"])


def test_identity_rejects_forged_or_malformed_bearer(tmp_path):
    identities=TenantIdentityStore(str(tmp_path/"tenant.sqlite3"))
    with pytest.raises(PermissionError):
        identities.authenticate("forged."+"x"*80)


def test_application_membership_revocation_is_immediate(tmp_path):
    path=str(tmp_path/"tenant.sqlite3")
    identities=TenantIdentityStore(path)
    issued=identities.provision("Tenant A","UNIBUD","principal-a",["memory.write"])
    assert identities.revoke_membership(issued["tenant_id"],issued["application_id"],"principal-a")
    with pytest.raises(PermissionError):
        identities.authenticate(issued["secret"])


def test_tenant_store_scopes_conversations_and_memory(tmp_path):
    path=str(tmp_path/"tenant.sqlite3")
    ids=TenantIdentityStore(path)
    a=ids.provision("Tenant A","UNIBUD","principal-a",["conversation.write","conversation.read","memory.write"])
    b=ids.provision("Tenant B","WAYWARD","principal-b",["conversation.write","conversation.read","memory.write"])
    ia,ib=ids.authenticate(a["secret"]),ids.authenticate(b["secret"])
    store=TenantStore(path)
    cid=store.create_conversation(ia,"private")
    store.add_message(ia,cid,"user","Tenant A only")
    with pytest.raises(LookupError):
        store.get_messages(ib,cid)
    mid=store.save_memory(ia,"Private academic context","learning")
    assert mid
    assert store.get_messages(ia,cid)[0]["content"]=="Tenant A only"


def test_memory_sharing_is_scoped_category_limited_and_revocable(tmp_path):
    path=str(tmp_path/"tenant.sqlite3")
    ids=TenantIdentityStore(path)
    source=ids.provision("Tenant A","UNIBUD","principal-a",["memory.write","memory.share"])
    destination=ids.provision_application(source["tenant_id"],"WAYWARD","principal-a",["memory.shared.read"])
    src,dst=ids.authenticate(source["secret"]),ids.authenticate(destination["secret"])
    store=TenantStore(path)
    store.save_memory(src,"Can be shared","preferences")
    store.save_memory(src,"Must stay private","sensitive") if "memory.sensitive.write" in src.capabilities else None
    grant=store.create_memory_grant(src,dst.application_id,["preferences"],"User-approved personalization",src.issued_at+3600)
    visible=store.shared_memories(dst,src.application_id)
    assert [item["content"] for item in visible]==["Can be shared"]
    assert store.revoke_memory_grant(src,grant)
    assert store.shared_memories(dst,src.application_id)==[]

def test_spark_memory_read_update_delete_are_principal_and_app_scoped(tmp_path):
    path=str(tmp_path/"tenant.sqlite3")
    ids=TenantIdentityStore(path)
    issued=ids.provision("Tenant A","UNIBUD","principal-a",
        ["memory.write","memory.read","memory.delete"])
    other=ids.provision("Tenant B","WAYWARD","principal-b",
        ["memory.write","memory.read","memory.delete"])
    identity=ids.authenticate(issued["secret"])
    other_identity=ids.authenticate(other["secret"])
    store=TenantStore(path)
    memory_id=store.save_memory(identity,"First version","learning")
    assert store.list_memories(identity)[0]["content"]=="First version"
    assert store.update_memory(identity,memory_id,"Corrected version","projects")
    assert store.list_memories(identity)[0]["content"]=="Corrected version"
    assert store.list_memories(other_identity)==[]
    assert store.delete_memory(identity,memory_id)
    assert store.list_memories(identity)==[]

def test_worker_revalidates_revocation_and_required_capabilities(tmp_path):
    from core.tenant_execution import TenantExecutionGuard
    path=str(tmp_path/"tenant.sqlite3")
    identities=TenantIdentityStore(path)
    issued=identities.provision("Tenant A","UNIBUD","principal-a",
        ["agent.oracle.dispatch","reasoning"])
    identity=identities.authenticate(issued["secret"])
    guard=TenantExecutionGuard(identities)
    assert guard.authorize(identity,("agent.oracle.dispatch","reasoning"))==identity
    assert identities.revoke(issued["credential_id"])
    with pytest.raises(PermissionError,match="authorization failed"):
        guard.authorize(identity,("agent.oracle.dispatch",))


def test_worker_revalidation_rejects_membership_revocation(tmp_path):
    from core.tenant_execution import TenantExecutionGuard
    path=str(tmp_path/"tenant.sqlite3")
    identities=TenantIdentityStore(path)
    issued=identities.provision("Tenant A","UNIBUD","principal-a",["agent.oracle.dispatch"])
    identity=identities.authenticate(issued["secret"])
    identities.revoke_membership(issued["tenant_id"],issued["application_id"],"principal-a")
    with pytest.raises(PermissionError):
        TenantExecutionGuard(identities).authorize(identity,("agent.oracle.dispatch",))



def test_sensitive_memories_cannot_be_shared_even_with_explicit_grant(tmp_path):
    path=str(tmp_path/"tenant.sqlite3")
    ids=TenantIdentityStore(path)
    source=ids.provision("Tenant A","UNIBUD","principal-a",
        ["memory.write","memory.sensitive.write","memory.share"])
    destination=ids.provision_application(source["tenant_id"],"WAYWARD","principal-a",
        ["memory.shared.read"])
    src,dst=ids.authenticate(source["secret"]),ids.authenticate(destination["secret"])
    store=TenantStore(path)
    store.save_memory(src,"Highly private","sensitive")
    with pytest.raises(ValueError,match="sensitive memories cannot be shared"):
        store.create_memory_grant(src,dst.application_id,["sensitive"],
            "Attempted sensitive sharing",src.issued_at+3600)
    grant=store.create_memory_grant(src,dst.application_id,["preferences"],
        "Share only preferences",src.issued_at+3600)
    assert store.shared_memories(dst,src.application_id)==[]
