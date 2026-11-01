import pytest
from fastapi.testclient import TestClient
import api


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv("ORACLE_ARC_API_KEY","owner-test-secret-0123456789-abcdef")
    monkeypatch.setenv("ORACLE_ARC_DB_PATH",str(tmp_path/"platform.sqlite3"))
    with TestClient(api.app) as c:
        yield c


def owner():
    return {"Authorization":"Bearer owner-test-secret-0123456789-abcdef"}


def test_owner_provisions_scoped_application_credential_and_spark_memory(client):
    tenant=client.post("/v1/platform/tenants",headers=owner(),json={"name":"MY REALM"})
    assert tenant.status_code==201
    tenant_id=tenant.json()["tenant_id"]
    app=client.post(f"/v1/platform/tenants/{tenant_id}/applications",
                    headers=owner(),json={"name":"UNIBUD"})
    assert app.status_code==201
    app_id=app.json()["application_id"]
    issued=client.post(
        f"/v1/platform/tenants/{tenant_id}/applications/{app_id}/credentials",
        headers=owner(),
        json={"principal_id":"student-1","capabilities":["spark.memory.read","spark.memory.write"]},
    )
    assert issued.status_code==201
    token=issued.json()["credential"]
    app_headers={"Authorization":"Bearer "+token}
    who=client.get("/v1/platform/identity",headers=app_headers)
    assert who.status_code==200
    assert who.json()["tenant_id"]==tenant_id
    assert who.json()["application_id"]==app_id
    saved=client.post("/v1/platform/memories",headers=app_headers,
                      json={"content":"My current project","category":"project"})
    assert saved.status_code==201
    listed=client.get("/v1/platform/memories",headers=app_headers)
    assert listed.status_code==200
    assert listed.json()["data"][0]["content"]=="My current project"
    # App credentials cannot be used as legacy owner credentials.
    assert client.get("/v1/memories",headers=app_headers).status_code==401


def test_platform_control_plane_requires_owner_and_app_routes_require_app_token(client):
    assert client.post("/v1/platform/tenants",json={"name":"No auth"}).status_code==401
    assert client.get("/v1/platform/identity").status_code==401


def test_revoked_application_credential_is_rejected(client):
    tenant=client.post("/v1/platform/tenants",headers=owner(),json={"name":"Tenant"}).json()["tenant_id"]
    app=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),
                    json={"name":"App"}).json()["application_id"]
    token=client.post(f"/v1/platform/tenants/{tenant}/applications/{app}/credentials",
                      headers=owner(),json={"principal_id":"p1","capabilities":["spark.memory.read"]}).json()["credential"]
    credential_id=token.split(".",1)[0]
    revoked=client.delete(f"/v1/platform/credentials/{credential_id}",headers=owner())
    assert revoked.status_code==200
    assert client.get("/v1/platform/identity",headers={"Authorization":"Bearer "+token}).status_code==401


def test_scoped_agent_task_api_enforces_application_boundary(client):
    tenant=client.post("/v1/platform/tenants",headers=owner(),json={"name":"Tenant"}).json()["tenant_id"]
    app_a=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),json={"name":"A"}).json()["application_id"]
    app_b=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),json={"name":"B"}).json()["application_id"]
    caps=["agent.oracle.dispatch","reasoning"]
    token_a=client.post(f"/v1/platform/tenants/{tenant}/applications/{app_a}/credentials",
        headers=owner(),json={"principal_id":"p1","capabilities":caps}).json()["credential"]
    token_b=client.post(f"/v1/platform/tenants/{tenant}/applications/{app_b}/credentials",
        headers=owner(),json={"principal_id":"p1","capabilities":caps}).json()["credential"]
    ha={"Authorization":"Bearer "+token_a}
    hb={"Authorization":"Bearer "+token_b}
    created=client.post("/v1/platform/agent-tasks",headers=ha,
        json={"agent_id":"oracle","required_capabilities":["reasoning"],"payload":{"prompt":"analyze"}})
    assert created.status_code==202
    task_id=created.json()["task_id"]
    assert client.get(f"/v1/platform/agent-tasks/{task_id}",headers=hb).status_code==404
    claim=client.post(f"/v1/platform/agent-tasks/{task_id}/claim?worker_id=worker-a",headers=ha)
    assert claim.status_code==200
    complete=client.post(f"/v1/platform/agent-tasks/{task_id}/complete",headers=ha,
        json={"worker_id":"worker-a","status":"succeeded","result":{"answer":"done"}})
    assert complete.status_code==200


def test_concierge_plan_is_allowed_but_execution_fails_closed_without_provider(client):
    tenant=client.post("/v1/platform/tenants",headers=owner(),json={"name":"Tenant"}).json()["tenant_id"]
    app=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),json={"name":"App"}).json()["application_id"]
    token=client.post(f"/v1/platform/tenants/{tenant}/applications/{app}/credentials",
        headers=owner(),json={"principal_id":"p1","capabilities":["concierge.workflow.plan","concierge.action.execute"]}).json()["credential"]
    headers={"Authorization":"Bearer "+token}
    plan=client.post("/v1/platform/concierge/workflows",headers=headers,json={
        "action":{"kind":"booking.create","provider":"not-configured",
                  "parameters":{"slot":"10:00"},"consequential":True}
    })
    assert plan.status_code==201
    confirm=client.post(f"/v1/platform/concierge/workflows/{plan.json()['workflow_id']}/confirm",
        headers=headers,json={"action_fingerprint":plan.json()["action_fingerprint"]})
    assert confirm.status_code==503



def test_developer_runtime_api_registers_routes_agents_workers_and_queues(client):
    tenant = client.post("/v1/platform/tenants", headers=owner(),
                         json={"name": "Developer Tenant"}).json()["tenant_id"]
    app_id = client.post(f"/v1/platform/tenants/{tenant}/applications", headers=owner(),
                         json={"name": "Research App"}).json()["application_id"]
    capabilities = [
        "agent.register", "agent.read", "agent.manage", "agent.execute",
        "agent.execution.read", "model.route.manage", "model.route.use",
        "quota.manage", "usage.write", "usage.read", "reasoning",
        "worker.register", "worker.manage",
    ]
    issued = client.post(
        f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(),
        json={"principal_id": "developer-1", "capabilities": capabilities},
    )
    assert issued.status_code == 201
    headers = {"Authorization": "Bearer " + issued.json()["credential"]}

    route = client.put("/v1/platform/model-routes/local-default", headers=headers, json={
        "route_id": "local-default", "provider_id": "ollama", "model_id": "qwen2.5:7b",
        "data_classifications": ["public", "internal", "private"], "regions": ["local"],
    })
    assert route.status_code == 200
    quota = client.put("/v1/platform/quotas", headers=headers, json={
        "window_seconds": 60, "max_executions": 10, "max_concurrent": 2,
        "max_input_bytes": 4096,
    })
    assert quota.status_code == 200
    published = client.post("/v1/platform/agents/versions", headers=headers, json={
        "agent_id": "research", "version": "1.0.0",
        "manifest": {
            "display_name": "Research", "description": "Research agent",
            "required_capabilities": ["reasoning"], "allowed_tools": [],
            "model_routes": ["local-default"], "runtime": "oracle-arc-agent-v1",
        },
    })
    assert published.status_code == 201
    worker = client.post("/v1/platform/workers", headers=headers, json={
        "runtime_ids": ["oracle-arc-agent-v1"], "ttl_seconds": 3600,
    })
    assert worker.status_code == 201
    assert worker.json()["shown_once"] is True
    submitted = client.post("/v1/platform/executions", headers=headers, json={
        "agent_id": "research", "agent_version": "1.0.0",
        "route_id": "local-default",
        "payload": {"messages": [{"role": "user", "content": "Explain model routing."}]},
        "classification": "private", "region": "local",
        "idempotency_key": "developer-api-test-1",
    })
    assert submitted.status_code == 202
    execution_id = submitted.json()["execution_id"]
    read = client.get(f"/v1/platform/executions/{execution_id}", headers=headers)
    assert read.status_code == 200
    assert read.json()["route_id"] == "local-default"
    audit = client.get(
        f"/v1/platform/executions/{execution_id}/tool-invocations", headers=headers)
    assert audit.status_code == 200
    assert audit.json() == {"execution_id": execution_id, "invocations": []}
    assert client.get("/v1/platform/usage", headers=headers).status_code == 200


def test_remote_agent_api_requires_explicit_residency_and_classification(client):
    tenant = client.post("/v1/platform/tenants", headers=owner(),
                         json={"name": "Remote Tenant"}).json()["tenant_id"]
    app_id = client.post(f"/v1/platform/tenants/{tenant}/applications", headers=owner(),
                         json={"name": "Remote App"}).json()["application_id"]
    capabilities = ["agent.register", "agent.execute", "model.route.manage",
                    "model.route.use", "quota.manage", "agent.execution.read",
                    "reasoning"]
    token = client.post(
        f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(), json={"principal_id": "remote-dev", "capabilities": capabilities},
    ).json()["credential"]
    headers = {"Authorization": "Bearer " + token}
    assert client.put("/v1/platform/model-routes/remote-default", headers=headers, json={
        "route_id": "remote-default", "provider_id": "groq", "model_id": "llama-3.3-70b-versatile",
        "data_classifications": ["public", "internal", "private"], "regions": ["unspecified"],
    }).status_code == 200
    assert client.put("/v1/platform/quotas", headers=headers, json={
        "window_seconds": 60, "max_executions": 10, "max_concurrent": 2,
        "max_input_bytes": 4096,
    }).status_code == 200
    published = client.post("/v1/platform/agents/versions", headers=headers, json={
        "agent_id": "remote-research", "version": "1.0.0",
        "manifest": {
            "display_name": "Remote Research", "description": "Remote research agent",
            "required_capabilities": ["reasoning"], "allowed_tools": [],
            "model_routes": ["remote-default"], "runtime": "oracle-arc-remote-agent-v1",
        },
    })
    assert published.status_code == 201
    rejected = client.post("/v1/platform/executions", headers=headers, json={
        "agent_id": "remote-research", "agent_version": "1.0.0",
        "route_id": "remote-default",
        "payload": {"messages": [{"role": "user", "content": "hello"}]},
        "classification": "sensitive", "region": "unspecified",
    })
    assert rejected.status_code == 403
    accepted = client.post("/v1/platform/executions", headers=headers, json={
        "agent_id": "remote-research", "agent_version": "1.0.0",
        "route_id": "remote-default",
        "payload": {"messages": [{"role": "user", "content": "hello"}]},
        "classification": "private", "region": "unspecified",
    })
    assert accepted.status_code == 202


def test_local_model_discovery_requires_explicit_read_capability(client, monkeypatch):
    from core import platform_routes
    tenant = client.post("/v1/platform/tenants", headers=owner(),
                         json={"name": "Discovery Tenant"}).json()["tenant_id"]
    app_id = client.post(f"/v1/platform/tenants/{tenant}/applications", headers=owner(),
                         json={"name": "Discovery App"}).json()["application_id"]

    def issue(capabilities):
        return client.post(
            f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
            headers=owner(), json={"principal_id": "discovery-user",
                                   "capabilities": capabilities}).json()["credential"]

    denied = {"Authorization": "Bearer " + issue(["agent.read"])}
    assert client.get("/v1/platform/models/discovered", headers=denied).status_code == 403
    allowed = {"Authorization": "Bearer " + issue(["model.route.read"])}

    class FakeDiscovery:
        def __init__(self, host):
            assert host == "http://127.0.0.1:11434"

        def public_inventory(self, limit):
            assert limit == 10
            return [{"model_id": "test-model", "capabilities": {"text": True}}]

        def health(self):
            from core.model_discovery import ProviderHealth
            return ProviderHealth("ollama", True, "ready", "test-version")

    monkeypatch.setattr(platform_routes, "LocalOllamaDiscovery", FakeDiscovery)
    inventory = client.get("/v1/platform/models/discovered?limit=10", headers=allowed)
    assert inventory.status_code == 200
    assert inventory.json()["models"][0]["model_id"] == "test-model"
    health = client.get("/v1/platform/providers/ollama/health", headers=allowed)
    assert health.status_code == 200
    assert health.json()["healthy"] is True
