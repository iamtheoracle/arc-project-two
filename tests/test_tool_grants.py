import pytest
from core.tenant_identity import TenantIdentityStore
from core.tool_grants import ToolGrantStore
from core.platform_control_plane import PlatformControlPlane

def provision(path):
 ids=TenantIdentityStore(str(path)); issued=ids.provision("Tenant A","Arc App","principal-a",["agent.register","agent.read","reasoning","model.route.manage","tool.calculate"])
 return ids,issued,ids.authenticate(issued["secret"])

def manifest(tools):
 return {"display_name":"Research","description":"Scoped agent","required_capabilities":["reasoning"],"allowed_tools":tools,"model_routes":["local-default"],"runtime":"oracle-arc-agent-v1"}

def test_owner_grant_and_revocation_are_audited_and_live(tmp_path):
 path=tmp_path/"arc.sqlite";ids,issued,identity=provision(path);grants=ToolGrantStore(str(path))
 grant=grants.grant(identity.tenant_id,identity.application_id,"tool.calculate","owner")
 assert grants.active_tool_ids(identity.tenant_id,identity.application_id)=={"tool.calculate"}
 assert grants.revoke(grant["grant_id"],"owner") is True
 assert grants.active_tool_ids(identity.tenant_id,identity.application_id)==set()
 assert grants.revoke(grant["grant_id"],"owner") is False
 history=grants.list(identity.tenant_id,identity.application_id)
 assert [x["status"] for x in history]==["revoked"]

def test_agent_manifest_cannot_self_grant_tool(tmp_path):
 path=tmp_path/"arc.sqlite";ids,issued,identity=provision(path);cp=PlatformControlPlane(str(path))
 cp.configure_model_route(identity,"local-default","ollama","qwen2.5:7b",["private"],["local"])
 with pytest.raises(PermissionError,match="owner grant"):
  cp.register_agent(identity,"research","1.0.0",manifest(["tool.calculate"]))

def test_revoked_owner_grant_blocks_new_agent_versions(tmp_path):
 path=tmp_path/"arc.sqlite";ids,issued,identity=provision(path);cp=PlatformControlPlane(str(path))
 cp.configure_model_route(identity,"local-default","ollama","qwen2.5:7b",["private"],["local"])
 store=ToolGrantStore(str(path));g=store.grant(identity.tenant_id,identity.application_id,"tool.calculate","owner")
 cp.register_agent(identity,"research","1.0.0",manifest(["tool.calculate"]))
 store.revoke(g["grant_id"],"owner")
 with pytest.raises(PermissionError,match="owner grant"):
  cp.register_agent(identity,"research","1.1.0",manifest(["tool.calculate"]))

def test_grants_are_tenant_application_scoped(tmp_path):
 path=tmp_path/"arc.sqlite";ids,issued,identity=provision(path);store=ToolGrantStore(str(path))
 g=store.grant(identity.tenant_id,identity.application_id,"tool.calculate","owner")
 assert store.active_tool_ids("another-tenant",identity.application_id)==set()
 assert store.active_tool_ids(identity.tenant_id,"another-app")==set()
 assert g["status"]=="active"
