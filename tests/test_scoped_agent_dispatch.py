import pytest
from core.agent_registry import AgentRegistry, AgentDefinition, Connector, RegistryError
from core.tenant_security import RequestIdentity


def test_agent_registry_rejects_unscoped_connectors_for_application_dispatch():
    registry=AgentRegistry()
    registry.register_agent(AgentDefinition("oracle","ORACLE","reasoning",("reasoning",)))
    registry.register_connector("oracle",Connector("legacy","local",0,lambda payload:"unsafe"))
    identity=RequestIdentity("cred","tenant","app","principal",
                             frozenset({"agent.oracle.dispatch","reasoning"}),1)
    with pytest.raises(RegistryError,match="tenant-scoped"):
        registry.dispatch_scoped(identity,"oracle",{"prompt":"test"},("reasoning",))


def test_agent_registry_passes_trusted_context_only_to_scoped_connector():
    registry=AgentRegistry()
    registry.register_agent(AgentDefinition("oracle","ORACLE","reasoning",("reasoning",)))
    seen={}
    def handler(payload):
        seen.update(payload["_oracle_request_context"])
        return "scoped result"
    registry.register_connector("oracle",Connector(
        "scoped","local",0,handler,supports_scoped_context=True))
    identity=RequestIdentity("cred","tenant-1","app-1","principal-1",
                             frozenset({"agent.oracle.dispatch","reasoning"}),7)
    result=registry.dispatch_scoped(identity,"oracle",{"prompt":"test"},("reasoning",))
    assert result["result"]=="scoped result"
    assert seen=={
        "tenant_id":"tenant-1","application_id":"app-1","principal_id":"principal-1",
        "policy_version":7,"capabilities":["agent.oracle.dispatch","reasoning"]
    }


def test_agent_registry_rejects_missing_dispatch_or_task_capabilities():
    registry=AgentRegistry()
    registry.register_agent(AgentDefinition("oracle","ORACLE","reasoning",("reasoning",)))
    identity=RequestIdentity("cred","tenant","app","principal",frozenset({"reasoning"}),1)
    with pytest.raises(RegistryError):
        registry.dispatch_scoped(identity,"oracle",{"prompt":"test"},("reasoning",))
