import pytest
import base64
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


def test_authenticated_document_ingestion_search_and_delete_api(client):
    tenant=client.post("/v1/platform/tenants",headers=owner(),json={"name":"Docs tenant"}).json()["tenant_id"]
    app_id=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),
                       json={"name":"Docs app"}).json()["application_id"]
    token=client.post(f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(),json={"principal_id":"student-1","capabilities":[
            "document.index","document.search","document.delete"
        ]}).json()["credential"]
    headers={"Authorization":"Bearer "+token}
    ingested=client.post("/v1/platform/documents",headers=headers,json={
        "title":"Course handbook","source_uri":"arc://uploads/handbook-1",
        "content":"The university handbook explains course registration and examination rules.",
        "classification":"private",
    })
    assert ingested.status_code==201
    document_id=ingested.json()["document_id"]
    searched=client.get("/v1/platform/documents/search",headers=headers,
                        params={"query":"course registration"})
    assert searched.status_code==200
    assert searched.json()["count"]==1
    assert searched.json()["data"][0]["document_id"]==document_id
    assert searched.json()["data"][0]["source_uri"]=="arc://uploads/handbook-1"
    deleted=client.delete(f"/v1/platform/documents/{document_id}",headers=headers)
    assert deleted.status_code==200
    assert client.get("/v1/platform/documents/search",headers=headers,
                      params={"query":"course registration"}).json()["count"]==0


def test_document_ingestion_api_requires_document_capability_and_rejects_unsafe_source(client):
    tenant=client.post("/v1/platform/tenants",headers=owner(),json={"name":"No docs tenant"}).json()["tenant_id"]
    app_id=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),
                       json={"name":"No docs app"}).json()["application_id"]
    token=client.post(f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(),json={"principal_id":"student-2","capabilities":["document.search"]}).json()["credential"]
    headers={"Authorization":"Bearer "+token}
    denied=client.post("/v1/platform/documents",headers=headers,json={
        "title":"Private note","source_uri":"https://example.test/note","content":"some extracted text",
    })
    assert denied.status_code==403
    unsafe=client.post("/v1/platform/documents",headers={
        "Authorization":"Bearer "+client.post(
            f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
            headers=owner(),json={"principal_id":"student-3","capabilities":["document.index"]}
        ).json()["credential"]
    },json={"title":"Unsafe","source_uri":"file:///etc/passwd","content":"not allowed"})
    assert unsafe.status_code==422


def test_orbits_api_runs_registered_processor_and_indexes_extracted_text(client,monkeypatch,tmp_path):
    import base64
    import core.platform_routes as routes
    from core.orbits import build_default_orbits_registry

    tenant=client.post("/v1/platform/tenants",headers=owner(),json={"name":"ORBITS tenant"}).json()["tenant_id"]
    app_id=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),
                       json={"name":"ORBITS app"}).json()["application_id"]
    token=client.post(f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(),json={"principal_id":"student-1","capabilities":[
            "orbits.process","image.ocr","document.index","document.search"
        ]}).json()["credential"]
    headers={"Authorization":"Bearer "+token}
    registry=build_default_orbits_registry(
        runner=lambda processor_id,data: {
            "media_type":"image","format":"image-ocr","width":20,"height":10,
            "text":"The campus handbook explains course registration deadlines."
        }
    )
    monkeypatch.setattr(routes,"build_default_orbits_registry",lambda:registry)
    monkeypatch.setattr(routes,"clamav_scan",lambda path:"ClamAV clean")
    monkeypatch.setenv("ORACLE_ARC_QUARANTINE_DIR",str(tmp_path/"quarantine"))
    raw=b"\x89PNG\r\n\x1a\nmock-image"
    response=client.post("/v1/platform/orbits/process",headers=headers,json={
        "processor_id":"image.ocr","filename":"handbook.png","mime_type":"image/png",
        "data_base64":base64.b64encode(raw).decode("ascii"),"index_text":True,
        "title":"Campus handbook","source_uri":"arc://uploads/campus-handbook",
    })
    assert response.status_code==200
    assert response.json()["quarantine_status"]=="clean"
    assert response.json()["expires_at"]>0
    assert response.json()["indexed"] is True
    assert response.json()["result"]["text"].startswith("The campus handbook")
    found=client.get("/v1/platform/documents/search",headers=headers,
                     params={"query":"registration deadlines"})
    assert found.status_code==200
    assert found.json()["count"]==1
    assert found.json()["data"][0]["source_uri"]=="arc://uploads/campus-handbook"


def test_orbits_api_scans_image_before_processing_and_fails_closed_on_malware(client,monkeypatch,tmp_path):
    import base64
    import core.platform_routes as routes
    from core.orbits import build_default_orbits_registry

    tenant=client.post("/v1/platform/tenants",headers=owner(),json={"name":"Scan tenant"}).json()["tenant_id"]
    app_id=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),json={"name":"Scan app"}).json()["application_id"]
    token=client.post(f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(),json={"principal_id":"student-scan","capabilities":["orbits.process","image.ocr"]}).json()["credential"]
    invoked={"processor":False}
    registry=build_default_orbits_registry(runner=lambda processor_id,data: invoked.update(processor=True) or {
        "media_type":"image","format":"image-ocr","width":2,"height":2,"text":"never reached"
    })
    monkeypatch.setattr(routes,"build_default_orbits_registry",lambda:registry)
    monkeypatch.setattr(routes,"clamav_scan",lambda path: (_ for _ in ()).throw(routes.MalwareDetected("test malware")))
    monkeypatch.setenv("ORACLE_ARC_QUARANTINE_DIR",str(tmp_path/"infected"))
    raw=b"\\x89PNG\\r\\n\\x1a\\nscan-me"
    response=client.post("/v1/platform/orbits/process",headers={"Authorization":"Bearer "+token},json={
        "processor_id":"image.ocr","filename":"scan.png","mime_type":"image/png",
        "data_base64":base64.b64encode(raw).decode("ascii"),
    })
    assert response.status_code==422
    assert invoked["processor"] is False


def test_orbits_api_scanner_unavailable_fails_closed_before_processing(client,monkeypatch,tmp_path):
    import base64
    import core.platform_routes as routes
    from core.orbits import build_default_orbits_registry

    tenant=client.post("/v1/platform/tenants",headers=owner(),json={"name":"Offline scanner tenant"}).json()["tenant_id"]
    app_id=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),json={"name":"Offline scanner app"}).json()["application_id"]
    token=client.post(f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(),json={"principal_id":"student-offline","capabilities":["orbits.process","image.ocr"]}).json()["credential"]
    invoked={"processor":False}
    registry=build_default_orbits_registry(runner=lambda processor_id,data: invoked.update(processor=True) or {
        "media_type":"image","format":"image-ocr","width":2,"height":2,"text":"never reached"
    })
    monkeypatch.setattr(routes,"build_default_orbits_registry",lambda:registry)
    monkeypatch.setattr(routes,"clamav_scan",lambda path: (_ for _ in ()).throw(routes.MalwareScannerUnavailable("offline")))
    monkeypatch.setenv("ORACLE_ARC_QUARANTINE_DIR",str(tmp_path/"offline"))
    raw=b"\\x89PNG\\r\\n\\x1a\\nscan-me"
    response=client.post("/v1/platform/orbits/process",headers={"Authorization":"Bearer "+token},json={
        "processor_id":"image.ocr","filename":"scan.png","mime_type":"image/png",
        "data_base64":base64.b64encode(raw).decode("ascii"),
    })
    assert response.status_code==503
    assert invoked["processor"] is False

def test_orbits_api_denies_processing_without_explicit_capability(client):
    import base64
    tenant=client.post("/v1/platform/tenants",headers=owner(),json={"name":"No ORBITS tenant"}).json()["tenant_id"]
    app_id=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),
                       json={"name":"No ORBITS app"}).json()["application_id"]
    token=client.post(f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(),json={"principal_id":"student-2","capabilities":["document.index"]}).json()["credential"]
    response=client.post("/v1/platform/orbits/process",headers={"Authorization":"Bearer "+token},json={
        "processor_id":"image.ocr","filename":"x.png","data_base64":base64.b64encode(
            b"\x89PNG\r\n\x1a\nmock"
        ).decode("ascii")
    })
    assert response.status_code==403


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
    app_a=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),json={"name":"App A"}).json()["application_id"]
    app_b=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),json={"name":"App B"}).json()["application_id"]
    caps=["agent.oracle.dispatch","agent.tasks.claim","agent.tasks.complete","reasoning"]
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
            "usage.read","reasoning","tool.calculate"
        ]})
    assert issued.status_code==201
    app_headers={"Authorization":"Bearer "+issued.json()["credential"]}

    # Owner governance must remain separate: an application bearer cannot list or mutate grants.
    grants_path="/v1/tenants/owner/tool-grants"
    assert client.get(grants_path,headers=app_headers).status_code==401
    granted=client.post(grants_path,headers=owner(),json={
        "tenant_id":tenant,"application_id":application,"tool_id":"tool.calculate"
    })
    assert granted.status_code==201,granted.text
    unsupported=client.post(grants_path,headers=owner(),json={
        "tenant_id":tenant,"application_id":application,"tool_id":"tool.unknown"
    })
    assert unsupported.status_code==422
    grant_id=granted.json()["grant_id"]

    route=client.put("/v1/platform/model-routes/local-default",headers=app_headers,json={
        "route_id":"local-default","provider_id":"ollama","model_id":"qwen2.5:7b",
        "data_classifications":["private"],"regions":["local"]
    })
    assert route.status_code==200,route.text
    manifest={
        "display_name":"Research","description":"Tenant-scoped research agent",
        "required_capabilities":["reasoning"],"allowed_tools":["tool.calculate"],
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

    snapshot=client.get("/v1/platform/executions",headers=ha)
    assert snapshot.status_code==200
    assert snapshot.json()["event_cursor"]>=1
    assert snapshot.json()["data"][0]["execution_id"]==queued.json()["execution_id"]

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


def test_document_upload_quarantines_scans_extracts_indexes_and_audits(client, monkeypatch):
    import core.platform_routes as platform_routes

    tenant = client.post("/v1/platform/tenants", headers=owner(),
                         json={"name": "Quarantine tenant"}).json()["tenant_id"]
    app_id = client.post(f"/v1/platform/tenants/{tenant}/applications", headers=owner(),
                         json={"name": "Quarantine app"}).json()["application_id"]
    token = client.post(
        f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(), json={"principal_id": "principal-q", "capabilities": [
            "orbits.process", "document.index", "document.search",
            "document.delete", "document.audit"
        ]},
    ).json()["credential"]
    headers = {"Authorization": "Bearer " + token}
    monkeypatch.setattr(platform_routes, "clamav_scan", lambda path: "ClamAV clean")
    class Registry:
        def process(self, processor_id, asset, data):
            assert processor_id == "document.extract"
            return {"text": data.decode("utf-8")}
    monkeypatch.setattr(platform_routes, "build_default_orbits_registry", lambda: Registry())
    data = b"Verified document ingestion evidence for Oracle Arc."
    uploaded = client.post("/v1/platform/documents/upload", headers=headers, json={
        "filename": "evidence.txt", "mime_type": "text/plain",
        "data_base64": base64.b64encode(data).decode("ascii"),
        "title": "Evidence", "source_uri": "arc://uploads/evidence",
        "retention_seconds": 3600,
    })
    assert uploaded.status_code == 201, uploaded.text
    payload = uploaded.json()
    assert payload["quarantine_status"] == "clean"
    assert payload["indexed"] is True
    asset_id = payload["asset_id"]
    searched = client.get("/v1/platform/documents/search", headers=headers,
                          params={"query": "ingestion evidence"})
    assert searched.status_code == 200
    assert searched.json()["count"] == 1
    audit = client.get(f"/v1/platform/documents/quarantine/{asset_id}/audit", headers=headers)
    assert audit.status_code == 200
    assert [event["action"] for event in audit.json()["events"]] == [
        "quarantined", "scanner_clean", "indexed_document_linked"
    ]
    deleted = client.delete(f"/v1/platform/documents/quarantine/{asset_id}", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/v1/platform/documents/search", headers=headers,
                      params={"query": "ingestion evidence"}).json()["count"] == 0
    audit = client.get(f"/v1/platform/documents/quarantine/{asset_id}/audit", headers=headers)
    assert audit.json()["events"][-1]["action"] == "owner_requested_bytes_deleted"
    after_delete = client.get("/v1/platform/documents/search", headers=headers,
                               params={"query": "ingestion evidence"})
    assert after_delete.status_code == 200
    assert after_delete.json()["count"] == 0


def test_document_upload_fails_closed_when_malware_scanner_is_unavailable(client, monkeypatch):
    import core.platform_routes as platform_routes
    from core.orbits_quarantine import MalwareScannerUnavailable

    tenant = client.post("/v1/platform/tenants", headers=owner(),
                         json={"name": "Scanner tenant"}).json()["tenant_id"]
    app_id = client.post(f"/v1/platform/tenants/{tenant}/applications", headers=owner(),
                         json={"name": "Scanner app"}).json()["application_id"]
    token = client.post(
        f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(), json={"principal_id": "principal-s", "capabilities": [
            "orbits.process", "document.index"
        ]},
    ).json()["credential"]
    monkeypatch.setattr(platform_routes, "clamav_scan",
                        lambda path: (_ for _ in ()).throw(MalwareScannerUnavailable("scanner offline")))
    response = client.post("/v1/platform/documents/upload",
        headers={"Authorization": "Bearer " + token}, json={
            "filename": "safe.txt", "data_base64": base64.b64encode(b"safe text").decode(),
            "title": "Safe", "source_uri": "arc://uploads/safe",
        })
    assert response.status_code == 503


def test_generic_orbits_endpoint_cannot_bypass_document_quarantine(client, monkeypatch):
    import core.platform_routes as platform_routes

    tenant = client.post("/v1/platform/tenants", headers=owner(),
                         json={"name": "Quarantine bypass tenant"}).json()["tenant_id"]
    app_id = client.post(f"/v1/platform/tenants/{tenant}/applications", headers=owner(),
                         json={"name": "Quarantine bypass app"}).json()["application_id"]
    token = client.post(
        f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(), json={"principal_id": "principal-bypass", "capabilities": [
            "orbits.process", "document.extract", "document.index"
        ]},
    ).json()["credential"]

    class MustNotRun:
        def process(self, processor_id, asset, data):
            pytest.fail("Document processor ran without quarantine and malware scanning")

    monkeypatch.setattr(platform_routes, "build_default_orbits_registry", lambda: MustNotRun())
    response = client.post("/v1/platform/orbits/process",
        headers={"Authorization": "Bearer " + token}, json={
            "processor_id": "document.extract",
            "filename": "unscanned.txt",
            "mime_type": "text/plain",
            "data_base64": base64.b64encode(b"unscanned document").decode("ascii"),
        })
    assert response.status_code == 422
    assert "documents/upload" in response.json()["detail"]


def test_generic_orbits_rejects_document_media_even_for_other_processor(client, monkeypatch):
    import core.platform_routes as platform_routes

    tenant = client.post("/v1/platform/tenants", headers=owner(),
                         json={"name": "Quarantine media tenant"}).json()["tenant_id"]
    app_id = client.post(f"/v1/platform/tenants/{tenant}/applications", headers=owner(),
                         json={"name": "Quarantine media app"}).json()["application_id"]
    token = client.post(
        f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(), json={"principal_id": "principal-media", "capabilities": [
            "orbits.process", "document.extract"
        ]},
    ).json()["credential"]

    class MustNotRun:
        def process(self, processor_id, asset, data):
            pytest.fail("Document media reached a generic ORBITS processor")

    monkeypatch.setattr(platform_routes, "build_default_orbits_registry", lambda: MustNotRun())
    response = client.post("/v1/platform/orbits/process",
        headers={"Authorization": "Bearer " + token}, json={
            "processor_id": "image.ocr",
            "filename": "document.txt",
            "mime_type": "text/plain",
            "data_base64": base64.b64encode(b"document text").decode("ascii"),
        })
    assert response.status_code == 422


def test_generic_orbits_document_extraction_cannot_bypass_quarantine(client, monkeypatch):
    tenant = client.post("/v1/platform/tenants", headers=owner(),
                         json={"name": "Quarantine enforcement"}).json()["tenant_id"]
    app_id = client.post(f"/v1/platform/tenants/{tenant}/applications", headers=owner(),
                         json={"name": "Document workflow"}).json()["application_id"]
    token = client.post(
        f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(), json={"principal_id": "document-user", "capabilities": [
            "orbits.process", "document.extract", "document.index"
        ]},
    ).json()["credential"]
    response = client.post("/v1/platform/orbits/process",
        headers={"Authorization": "Bearer " + token}, json={
            "processor_id": "document.extract",
            "filename": "unscanned.txt", "mime_type": "text/plain",
            "data_base64": base64.b64encode(b"must be quarantined first").decode(),
            "index_text": True,
        })
    assert response.status_code == 403
    assert "quarantined document upload workflow" in response.json()["detail"]

def test_spark_grant_is_revoked_when_last_source_credential_is_revoked(client):
    tenant=client.post("/v1/platform/tenants",headers=owner(),json={"name":"SPARK revoke tenant"}).json()["tenant_id"]
    source=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),json={"name":"SPARK source"}).json()["application_id"]
    destination=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),json={"name":"SPARK destination"}).json()["application_id"]
    source_token=client.post(f"/v1/platform/tenants/{tenant}/applications/{source}/credentials",headers=owner(),
        json={"principal_id":"principal-1","capabilities":["spark.memory.write","spark.memory.share"]}).json()["credential"]
    destination_token=client.post(f"/v1/platform/tenants/{tenant}/applications/{destination}/credentials",headers=owner(),
        json={"principal_id":"principal-1","capabilities":["spark.memory.read_shared"]}).json()["credential"]
    source_headers={"Authorization":"Bearer "+source_token}
    destination_headers={"Authorization":"Bearer "+destination_token}
    saved=client.post("/v1/platform/memories",headers=source_headers,json={"content":"Only this principal may share this memory","category":"project"})
    assert saved.status_code==201
    grant=client.post("/v1/platform/memory-sharing-grants",headers=source_headers,json={
        "destination_application_id":destination,"categories":["project"],"purpose":"Authorized project continuity"
    })
    assert grant.status_code==201
    assert client.get(f"/v1/platform/shared-memories/{source}",headers=destination_headers).json()["data"]
    credential_id=source_token.split(".",1)[0]
    assert client.delete(f"/v1/platform/credentials/{credential_id}",headers=owner()).status_code==200
    assert client.get(f"/v1/platform/shared-memories/{source}",headers=destination_headers).json()["data"]==[]


def test_spark_grant_survives_revocation_when_source_has_another_live_credential(client):
    tenant=client.post("/v1/platform/tenants",headers=owner(),json={"name":"SPARK multi-key tenant"}).json()["tenant_id"]
    source=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),json={"name":"SPARK multi-key source"}).json()["application_id"]
    destination=client.post(f"/v1/platform/tenants/{tenant}/applications",headers=owner(),json={"name":"SPARK multi-key destination"}).json()["application_id"]
    first=client.post(f"/v1/platform/tenants/{tenant}/applications/{source}/credentials",headers=owner(),
        json={"principal_id":"principal-2","capabilities":["spark.memory.write","spark.memory.share"]}).json()["credential"]
    second=client.post(f"/v1/platform/tenants/{tenant}/applications/{source}/credentials",headers=owner(),
        json={"principal_id":"principal-2","capabilities":["spark.memory.write","spark.memory.share"]}).json()["credential"]
    # NULL expiry represents a credential that does not expire; it remains active.
    import os, sqlite3
    with sqlite3.connect(os.environ["ORACLE_ARC_DB_PATH"]) as db:
        db.execute("UPDATE arc_credentials SET expires_at=NULL WHERE credential_id=?",
                   (second.split(".",1)[0],))
    destination_token=client.post(f"/v1/platform/tenants/{tenant}/applications/{destination}/credentials",headers=owner(),
        json={"principal_id":"principal-2","capabilities":["spark.memory.read_shared"]}).json()["credential"]
    source_headers={"Authorization":"Bearer "+first}
    destination_headers={"Authorization":"Bearer "+destination_token}
    assert client.post("/v1/platform/memories",headers=source_headers,json={"content":"Grant stays while another key is live","category":"project"}).status_code==201
    grant=client.post("/v1/platform/memory-sharing-grants",headers=source_headers,json={
        "destination_application_id":destination,"categories":["project"],"purpose":"Authorized continuity"
    })
    assert grant.status_code==201
    first_id=first.split(".",1)[0]
    assert client.delete(f"/v1/platform/credentials/{first_id}",headers=owner()).status_code==200
    assert client.get(f"/v1/platform/shared-memories/{source}",headers=destination_headers).json()["data"]
    # The second source credential remains valid, so its principal-owned grant survives.
    assert client.get("/v1/platform/identity",headers={"Authorization":"Bearer "+second}).status_code==200



def test_voice_session_transcription_uses_local_asr_and_purges_clean_audio(client, monkeypatch, tmp_path):
    import base64
    import core.platform_routes as routes

    tenant = client.post("/v1/platform/tenants", headers=owner(),
                         json={"name": "Voice transcription tenant"}).json()["tenant_id"]
    app_id = client.post(f"/v1/platform/tenants/{tenant}/applications", headers=owner(),
                         json={"name": "Voice transcription app"}).json()["application_id"]
    token = client.post(
        f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(),
        json={"principal_id": "voice-owner", "capabilities": [
            "audio.capture", "audio.transcribe", "audio.read", "orbits.process"
        ]},
    ).json()["credential"]
    headers = {"Authorization": "Bearer " + token}
    created = client.post("/v1/platform/audio/sessions", headers=headers)
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    scan_order = []
    monkeypatch.setattr(routes, "clamav_scan", lambda path: scan_order.append("scan") or "ClamAV clean")
    class LocalASRRegistry:
        def process(self, processor_id, asset, data):
            scan_order.append("asr")
            assert processor_id == "audio.transcribe"
            assert asset.media_type == "audio"
            assert data.startswith(b"RIFF")
            return {
                "text": "The meeting starts at ten in the morning.",
                "language": "en",
                "duration_seconds": 3.2,
                "inference_location": "local",
            }

    monkeypatch.setattr(routes, "build_default_orbits_registry", lambda: LocalASRRegistry())
    quarantine_dir = tmp_path / "voice-quarantine"
    monkeypatch.setenv("ORACLE_ARC_QUARANTINE_DIR", str(quarantine_dir))
    audio = b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + (b"\x00" * 32)
    response = client.post(
        f"/v1/platform/audio/sessions/{session_id}/transcribe",
        headers=headers,
        json={
            "filename": "voice.wav",
            "mime_type": "audio/wav",
            "data_base64": base64.b64encode(audio).decode("ascii"),
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["transcript"] == "The meeting starts at ten in the morning."
    assert payload["inference_location"] == "local"
    assert payload["audio_retained"] is False
    assert payload["state"] == "awaiting_model"
    assert scan_order == ["scan", "asr"]
    assert list(quarantine_dir.iterdir()) == []

    events = client.get(
        f"/v1/platform/audio/sessions/{session_id}/events", headers=headers
    ).json()["events"]
    assert events[-1]["state"] == "awaiting_model"
    assert all("transcript" not in str(event).lower() for event in events)
    assert all("meeting starts" not in str(event) for event in events)


def test_voice_session_transcription_fails_closed_when_scanner_is_unavailable(client, monkeypatch, tmp_path):
    import base64
    import core.platform_routes as routes

    tenant = client.post("/v1/platform/tenants", headers=owner(),
                         json={"name": "Voice scanner tenant"}).json()["tenant_id"]
    app_id = client.post(f"/v1/platform/tenants/{tenant}/applications", headers=owner(),
                         json={"name": "Voice scanner app"}).json()["application_id"]
    token = client.post(
        f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(),
        json={"principal_id": "voice-scanner", "capabilities": [
            "audio.capture", "audio.transcribe", "audio.read", "orbits.process"
        ]},
    ).json()["credential"]
    headers = {"Authorization": "Bearer " + token}
    session_id = client.post("/v1/platform/audio/sessions", headers=headers).json()["session_id"]
    invoked = {"asr": False}
    class NeverASRRegistry:
        def process(self, processor_id, asset, data):
            invoked["asr"] = True
            return {"text": "must not run"}

    monkeypatch.setattr(routes, "build_default_orbits_registry", lambda: NeverASRRegistry())
    monkeypatch.setattr(
        routes, "clamav_scan",
        lambda path: (_ for _ in ()).throw(routes.MalwareScannerUnavailable("offline")),
    )
    monkeypatch.setenv("ORACLE_ARC_QUARANTINE_DIR", str(tmp_path / "voice-offline"))
    audio = b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + (b"\x00" * 32)
    response = client.post(
        f"/v1/platform/audio/sessions/{session_id}/transcribe",
        headers=headers,
        json={
            "filename": "voice.wav", "mime_type": "audio/wav",
            "data_base64": base64.b64encode(audio).decode("ascii"),
        },
    )
    assert response.status_code == 503
    assert invoked["asr"] is False
    session = client.get(f"/v1/platform/audio/sessions/{session_id}", headers=headers).json()
    assert session["state"] == "failed"



def _voice_app_identity(client, capabilities):
    tenant = client.post("/v1/platform/tenants", headers=owner(),
                         json={"name": "ORACLE voice turn tenant"}).json()["tenant_id"]
    app_id = client.post(f"/v1/platform/tenants/{tenant}/applications", headers=owner(),
                         json={"name": "ORACLE voice turn app"}).json()["application_id"]
    token = client.post(
        f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(),
        json={"principal_id": "voice-turn-owner", "capabilities": capabilities},
    ).json()["credential"]
    return {"Authorization": "Bearer " + token}, token


def _voice_session_awaiting_model(client, headers, token):
    import core.platform_routes as routes
    from core.voice_sessions import VoiceSessionStore
    session_id = client.post("/v1/platform/audio/sessions", headers=headers).json()["session_id"]
    identity = routes._store().authenticate(token)
    sessions = VoiceSessionStore(routes.os.environ["ORACLE_ARC_DB_PATH"])
    for state in ("capturing", "uploaded", "transcribing", "awaiting_model"):
        sessions.transition(identity, session_id, state)
    return session_id, identity, sessions


def test_voice_response_is_queued_through_oracle_execution_control_plane(client, monkeypatch):
    import core.platform_routes as routes

    headers, token = _voice_app_identity(client, [
        "audio.capture", "audio.read", "audio.transcribe", "agent.execute"
    ])
    session_id, identity, sessions = _voice_session_awaiting_model(client, headers, token)
    captured = {}

    class FakeControlPlane:
        def submit_execution(self, *args):
            captured["args"] = args
            return "exec_voice_12345678"

    monkeypatch.setattr(routes, "_control_plane", lambda: FakeControlPlane())
    response = client.post(
        f"/v1/platform/audio/sessions/{session_id}/respond",
        headers=headers,
        json={
            "transcript": "What is the deadline for course registration?",
            "agent_id": "oracle-agent", "agent_version": "1.0.0",
            "route_id": "local-default",
        },
    )
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["execution_id"] == "exec_voice_12345678"
    assert payload["status"] == "queued"
    args = captured["args"]
    assert args[0] == identity
    assert "spoken conversation" in args[4]["prompt"]
    assert args[4]["prompt"].endswith("User said: What is the deadline for course registration?")
    assert args[4]["input_mode"] == "voice"
    assert args[4]["voice_session_id"] == session_id
    assert args[7] == 2
    assert args[8].startswith("voice-" + session_id + "-")
    assert sessions.get(identity, session_id)["state"] == "awaiting_model"
    events = sessions.events(identity, session_id)
    assert events[-1]["event_type"] == "oracle.execution.queued"
    assert events[-1]["details"]["execution_id"] == "exec_voice_12345678"
    assert events[-1]["details"]["turn_id"].startswith("turn_")
    assert all("course registration" not in str(event) for event in events)


def test_voice_response_synthesizes_only_completed_scoped_oracle_output(client, monkeypatch):
    import json
    from types import SimpleNamespace
    import core.platform_routes as routes

    headers, token = _voice_app_identity(client, [
        "audio.capture", "audio.read", "audio.synthesize", "agent.execution.read"
    ])
    session_id, identity, sessions = _voice_session_awaiting_model(client, headers, token)
    sessions.record_event(identity, session_id, "oracle.execution.queued", {
        "execution_id": "exec_voice_12345678", "turn_id": "turn_12345678",
    })
    requested = {}

    class FakeControlPlane:
        def get_execution(self, who, execution_id):
            requested["identity"] = who
            requested["execution_id"] = execution_id
            return SimpleNamespace(
                status="succeeded",
                output_json=json.dumps({"content": "Your registration deadline is Friday."}),
                model_provider="ollama", model_id="qwen2.5:7b",
            )

    monkeypatch.setattr(routes, "_control_plane", lambda: FakeControlPlane())
    monkeypatch.setattr(
        "core.orbits_tts_runtime.run_local_tts",
        lambda text, voice_id: {
            "format": "audio/wav", "audio_base64": "UklGRg==",
            "sha256": "a" * 64, "inference_location": "local",
        },
    )
    response = client.post(
        f"/v1/platform/audio/sessions/{session_id}/speak",
        headers=headers,
        json={"execution_id": "exec_voice_12345678"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["text"] == "Your registration deadline is Friday."
    assert payload["state"] == "ready"
    assert payload["inference_location"] == "local"
    assert payload["retained"] is False
    assert requested["identity"] == identity
    assert requested["execution_id"] == "exec_voice_12345678"
    assert sessions.get(identity, session_id)["state"] == "ready"

    started = client.post(
        f"/v1/platform/audio/sessions/{session_id}/playback",
        headers=headers, json={"outcome": "started"},
    )
    assert started.status_code == 200
    completed = client.post(
        f"/v1/platform/audio/sessions/{session_id}/playback",
        headers=headers, json={"outcome": "completed"},
    )
    assert completed.status_code == 200
    assert completed.json()["state"] == "completed"
    events = sessions.events(identity, session_id)
    assert [event["state"] for event in events[-4:]] == [
        "synthesizing", "ready", "playing", "completed"
    ]


def test_voice_response_refuses_queued_or_failed_execution_without_synthesizing(client, monkeypatch):
    from types import SimpleNamespace
    import core.platform_routes as routes

    headers, token = _voice_app_identity(client, [
        "audio.capture", "audio.read", "audio.synthesize", "agent.execution.read"
    ])
    session_id, identity, sessions = _voice_session_awaiting_model(client, headers, token)
    sessions.record_event(identity, session_id, "oracle.execution.queued", {
        "execution_id": "exec_voice_12345678", "turn_id": "turn_12345678",
    })
    class FakeControlPlane:
        def get_execution(self, who, execution_id):
            return SimpleNamespace(status="running", output_json=None,
                                   model_provider="ollama", model_id="qwen2.5:7b")
    monkeypatch.setattr(routes, "_control_plane", lambda: FakeControlPlane())
    called = {"tts": False}
    monkeypatch.setattr(
        "core.orbits_tts_runtime.run_local_tts",
        lambda *args: called.update(tts=True),
    )
    response = client.post(
        f"/v1/platform/audio/sessions/{session_id}/speak",
        headers=headers, json={"execution_id": "exec_voice_12345678"},
    )
    assert response.status_code == 409
    assert called["tts"] is False
    assert sessions.get(identity, session_id)["state"] == "awaiting_model"



def test_voice_session_cannot_speak_an_execution_from_another_turn(client, monkeypatch):
    import core.platform_routes as routes

    headers, token = _voice_app_identity(client, [
        "audio.capture", "audio.read", "audio.synthesize", "agent.execution.read"
    ])
    session_id, identity, sessions = _voice_session_awaiting_model(client, headers, token)
    sessions.record_event(identity, session_id, "oracle.execution.queued", {
        "execution_id": "exec_voice_87654321", "turn_id": "turn_87654321",
    })

    class MustNotReadExecution:
        def get_execution(self, *args):
            raise AssertionError("Unlinked execution must not be read")

    monkeypatch.setattr(routes, "_control_plane", lambda: MustNotReadExecution())
    called = {"tts": False}
    monkeypatch.setattr(
        "core.orbits_tts_runtime.run_local_tts",
        lambda *args: called.update(tts=True),
    )
    response = client.post(
        f"/v1/platform/audio/sessions/{session_id}/speak",
        headers=headers, json={"execution_id": "exec_voice_12345678"},
    )
    assert response.status_code == 404
    assert called["tts"] is False
    assert sessions.get(identity, session_id)["state"] == "awaiting_model"


def test_concierge_workflow_status_api_returns_scoped_durable_history(client):
    tenant = client.post("/v1/platform/tenants", headers=owner(),
                         json={"name": "Concierge history tenant"}).json()["tenant_id"]
    app_id = client.post(f"/v1/platform/tenants/{tenant}/applications", headers=owner(),
                         json={"name": "Concierge history app"}).json()["application_id"]
    token = client.post(
        f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(), json={"principal_id": "concierge-user", "capabilities": [
            "concierge.workflow.plan", "concierge.workflow.read"
        ]},
    ).json()["credential"]
    headers = {"Authorization": "Bearer " + token}
    planned = client.post("/v1/platform/concierge/workflows", headers=headers, json={
        "action": {"kind": "booking.create", "provider": "unconfigured-provider",
                   "parameters": {"slot": "slot-1"}, "consequential": True}
    })
    assert planned.status_code == 201
    workflow_id = planned.json()["workflow_id"]
    history = client.get(f"/v1/platform/concierge/workflows/{workflow_id}", headers=headers)
    assert history.status_code == 200
    assert history.json()["status"] == "awaiting_confirmation"
    assert history.json()["provider_outcome"] == "not_started"
    assert history.json()["retry_allowed"] is True
    assert history.json()["events"][0]["event_type"] == "workflow.planned"


def test_concierge_cancel_api_requires_scoped_cancel_capability(client):
    tenant = client.post("/v1/platform/tenants", headers=owner(),
                         json={"name": "Concierge cancellation tenant"}).json()["tenant_id"]
    app_id = client.post(f"/v1/platform/tenants/{tenant}/applications", headers=owner(),
                         json={"name": "Concierge cancellation app"}).json()["application_id"]
    token = client.post(
        f"/v1/platform/tenants/{tenant}/applications/{app_id}/credentials",
        headers=owner(), json={"principal_id": "concierge-cancel-user", "capabilities": [
            "concierge.workflow.plan", "concierge.workflow.read", "concierge.workflow.cancel"
        ]},
    ).json()["credential"]
    headers = {"Authorization": "Bearer " + token}
    planned = client.post("/v1/platform/concierge/workflows", headers=headers, json={
        "action": {"kind": "booking.create", "provider": "provider",
                   "parameters": {"slot": "slot-cancel"}, "consequential": True}
    })
    workflow_id = planned.json()["workflow_id"]
    cancelled = client.post(f"/v1/platform/concierge/workflows/{workflow_id}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert client.get(f"/v1/platform/concierge/workflows/{workflow_id}", headers=headers).json()["status"] == "cancelled"
