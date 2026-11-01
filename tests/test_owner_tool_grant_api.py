import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.tenant_api import router
from core.tenant_identity import TenantIdentityStore

def test_tool_grant_api_requires_owner_secret_and_scopes_application(tmp_path,monkeypatch):
 db=str(tmp_path/"api.sqlite")
 identities=TenantIdentityStore(db)
 provisioned=identities.provision("API Tenant","Arc Console","owner-test",["agent.read"])
 monkeypatch.setenv("ORACLE_ARC_DB_PATH",db)
 monkeypatch.setenv("ORACLE_ARC_API_KEY","x"*48)
 app=FastAPI();app.include_router(router)
 client=TestClient(app)
 path="/v1/tenants/owner/tool-grants"
 assert client.get(path).status_code==401
 assert client.get(path,headers={"Authorization":"Bearer "+provisioned["secret"]}).status_code==401
 owner={"Authorization":"Bearer "+"x"*48}
 created=client.post(path,headers=owner,json={"tenant_id":provisioned["tenant_id"],"application_id":provisioned["application_id"],"tool_id":"tool.search"})
 assert created.status_code==201,created.text
 grant=created.json()
 assert grant["status"]=="active"
 listed=client.get(path,headers=owner,params={"tenant_id":provisioned["tenant_id"],"application_id":provisioned["application_id"]})
 assert listed.status_code==200 and len(listed.json()["data"])==1
 revoked=client.delete(path+"/"+grant["grant_id"],headers=owner)
 assert revoked.status_code==200 and revoked.json()["revoked"] is True
 assert client.delete(path+"/"+grant["grant_id"],headers=owner).status_code==404
