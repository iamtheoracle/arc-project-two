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


def test_project_one_application_identity_and_owner_tool_governance_share_the_live_platform(client):
    tenant=client.post("/v1/platform/tenants",headers=owner(),json={"name":"MY REALM"}).json()["tenant_id"]
    application=client.post(f"/v1/platform/tenants/{tenant}/applications",
        headers=owner(),json={"name":"Project One Console"}).json()["application_id"]
    issued=client.post(f"/v1/platform/tenants/{tenant}/applications/{application}/credentials",
        headers=owner(),json={"principal_id":"arc-console-owner","capabilities":[
            "agent.read","agent.register","agent.execute","agent.execution.read",
            "model.route.manage","model.route.use","quota.read","quota.manage",
            "usage.read","reasoning","tool.search"
        ]})
    assert issued.status_code==201
    app_headers={"Authorization":"Bearer "+issued.json()["credential"]}

    # Owner governance must remain separate: an application bearer cannot list or mutate grants.
    grants_path="/v1/tenants/owner/tool-grants"
    assert client.get(grants_path,headers=app_headers).status_code==401
    granted=client.post(grants_path,headers=owner(),json={
        "tenant_id":tenant,"application_id":application,"tool_id":"tool.search"
    })
    assert granted.status_code==201,granted.text
    grant_id=granted.json()["grant_id"]

    route=client.put("/v1/platform/model-routes/local-default",headers=app_headers,json={
        "route_id":"local-default","provider_id":"ollama","model_id":"qwen2.5:7b",
        "data_classifications":["private"],"regions":["local"]
    })
    assert route.status_code==200,route.text
    manifest={
        "display_name":"Research","description":"Tenant-scoped research agent",
        "required_capabilities":["reasoning"],"allowed_tools":["tool.search"],
        "model_routes":["local-default"],"runtime":"oracle-arc-agent-v1"
    }
    registered=client.post("/v1/platform/agents/versions",headers=app_headers,json={
        "agent_id":"research","version":"1.0.0","manifest":manifest
    })
    assert registered.status_code==201,registered.text

    revoked=client.delete(f"{grants_path}/{grant_id}",headers=owner())
    assert revoked.status_code==200 and revoked.json()["revoked"] is True
    blocked=client.post("/v1/platform/agents/versions",headers=app_headers,json={
        "agent_id":"research","version":"1.1.0","manifest":manifest
    })
    assert blocked.status_code==403
    history=client.get(grants_path,headers=owner(),params={
        "tenant_id":tenant,"application_id":application
    })
    assert history.status_code==200
    assert history.json()["data"][0]["status"]=="revoked"


def test_legacy_tenant_identity_schema_isolated_from_project_one_platform_schema(client,tmp_path):
    platform_tenant=client.post("/v1/platform/tenants",headers=owner(),
        json={"name":"Platform Tenant"})
    assert platform_tenant.status_code==201
    platform_app=client.post(
        f"/v1/platform/tenants/{platform_tenant.json()['tenant_id']}/applications",
        headers=owner(),json={"name":"Project One"}
    )
    assert platform_app.status_code==201
    platform_credential=client.post(
        f"/v1/platform/tenants/{platform_tenant.json()['tenant_id']}/applications/{platform_app.json()['application_id']}/credentials",
        headers=owner(),json={"principal_id":"platform-user","capabilities":["agent.read"]}
    )
    assert platform_credential.status_code==201

    # The legacy tenant API remains available but must not initialize incompatible
    # arc_credentials / arc_principals layouts in the platform database.
    legacy=client.post("/v1/tenants/provision",headers=owner(),json={
        "tenant_name":"Legacy Tenant","application_name":"Legacy App",
        "principal_id":"legacy-user","capabilities":["inference.chat"]
    })
    assert legacy.status_code==201,legacy.text
    legacy_identity=client.get("/v1/tenants/identity",
        headers={"Authorization":"Bearer "+legacy.json()["secret"]})
    assert legacy_identity.status_code==200

    platform_identity=client.get("/v1/platform/identity",
        headers={"Authorization":"Bearer "+platform_credential.json()["credential"]})
    assert platform_identity.status_code==200
    assert platform_identity.json()["application_id"]==platform_app.json()["application_id"]
    assert (tmp_path/"platform_tenant_identity.sqlite3").exists()


def test_execution_event_stream_replays_durable_events_only_to_the_owning_principal(client):
    tenant=client.post("/v1/platform/tenants",headers=owner(),json={"name":"Event tenant"}).json()["tenant_id"]
    app_a=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),
        json={"name":"Event owner"}).json()["application_id"]
    app_b=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),
        json={"name":"Other app"}).json()["application_id"]
    caps=["agent.read","agent.register","agent.execute","agent.execution.read",
          "model.route.manage","model.route.use","quota.manage","usage.read","reasoning"]
    token_a=client.post(f"/v1/platform/tenants/{tenant}/applications/{app_a}/credentials",
        headers=owner(),json={"principal_id":"event-owner","capabilities":caps}).json()["credential"]
    token_b=client.post(f"/v1/platform/tenants/{tenant}/applications/{app_b}/credentials",
        headers=owner(),json={"principal_id":"event-other","capabilities":caps}).json()["credential"]
    ha={"Authorization":"Bearer "+token_a}
    hb={"Authorization":"Bearer "+token_b}
    assert client.put("/v1/platform/model-routes/default",headers=ha,json={
        "route_id":"default","provider_id":"ollama","model_id":"qwen2.5:7b",
        "data_classifications":["private"],"regions":["local"]
    }).status_code==200
    assert client.put("/v1/platform/quotas",headers=ha,json={
        "window_seconds":60,"max_executions":10,"max_concurrent":2,"max_input_bytes":4096
    }).status_code==200
    manifest={"display_name":"Event agent","description":"Event test",
        "required_capabilities":["reasoning"],"allowed_tools":[],
        "model_routes":["default"],"runtime":"oracle-arc-agent-v1"}
    assert client.post("/v1/platform/agents/versions",headers=ha,json={
        "agent_id":"event-agent","version":"1.0.0","manifest":manifest
    }).status_code==201
    queued=client.post("/v1/platform/executions",headers=ha,json={
        "agent_id":"event-agent","agent_version":"1.0.0","route_id":"default",
        "payload":{"prompt":"hello"},"classification":"private","region":"local"
    })
    assert queued.status_code==202,queued.text

    own_stream=client.get("/v1/platform/executions/events",
        params={"after":0,"duration_seconds":1},headers=ha)
    assert own_stream.status_code==200
    assert own_stream.headers["content-type"].startswith("text/event-stream")
    assert "event: execution" in own_stream.text
    assert queued.json()["execution_id"] in own_stream.text

    other_stream=client.get("/v1/platform/executions/events",
        params={"after":0,"duration_seconds":1},headers=hb)
    assert other_stream.status_code==200
    assert "event: execution" not in other_stream.text
    assert queued.json()["execution_id"] not in other_stream.text
