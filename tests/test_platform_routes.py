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
