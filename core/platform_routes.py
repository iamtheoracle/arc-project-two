"""Scoped platform API for tenant/application credentials and SPARK memory.

Legacy owner routes remain owner-only. This router is the first application-credential
surface; it never accepts caller-supplied tenant/app/principal scope.
"""
from __future__ import annotations
import hmac
import os
from pathlib import Path
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from core.tenant_security import TenantSecurityStore, AuthorizationError

router=APIRouter(prefix="/v1/platform",tags=["platform-identity"])


def _store() -> TenantSecurityStore:
    return TenantSecurityStore(os.environ.get("ORACLE_ARC_DB_PATH","data/oracle_arc.sqlite3"))


def require_owner(authorization: str | None = Header(default=None)):
    expected=os.environ.get("ORACLE_ARC_API_KEY","").strip()
    scheme,_,token=(authorization or "").partition(" ")
    if not expected or len(expected)<32 or expected.startswith("replace-with-"):
        raise HTTPException(503,"Owner control-plane secret is not configured")
    if scheme.lower()!="bearer" or not hmac.compare_digest(token,expected):
        raise HTTPException(401,"Owner authentication required")


def require_application(authorization: str | None = Header(default=None)):
    scheme,_,token=(authorization or "").partition(" ")
    if scheme.lower()!="bearer" or not token:
        raise HTTPException(401,"Application credential required")
    try:
        return _store().authenticate(token)
    except AuthorizationError as exc:
        raise HTTPException(401,str(exc))


class TenantCreate(BaseModel):
    name:str=Field(min_length=2,max_length=160)

class ApplicationCreate(BaseModel):
    name:str=Field(min_length=2,max_length=160)

class CredentialCreate(BaseModel):
    principal_id:str=Field(min_length=1,max_length=128)
    capabilities:list[str]=Field(min_length=1,max_length=30)
    ttl_seconds:int=Field(default=86400,ge=60,le=31536000)

class MemoryCreate(BaseModel):
    content:str=Field(min_length=1,max_length=20000)
    category:str="preference"

class MemoryShareCreate(BaseModel):
    destination_application_id:str
    categories:list[str]=Field(min_length=1,max_length=3)
    purpose:str=Field(min_length=3,max_length=500)
    ttl_seconds:int=Field(default=86400,ge=60,le=31536000)


@router.post("/tenants",dependencies=[Depends(require_owner)],status_code=201)
def create_tenant(body:TenantCreate):
    return {"tenant_id":_store().create_tenant(body.name),"status":"active"}

@router.post("/tenants/{tenant_id}/applications",dependencies=[Depends(require_owner)],status_code=201)
def create_application(tenant_id:str,body:ApplicationCreate):
    try:
        app_id=_store().create_application(tenant_id,body.name)
        return {"application_id":app_id,"tenant_id":tenant_id,"status":"active"}
    except AuthorizationError as exc:
        raise HTTPException(404,str(exc))

@router.post("/tenants/{tenant_id}/applications/{application_id}/credentials",
             dependencies=[Depends(require_owner)],status_code=201)
def issue_credential(tenant_id:str,application_id:str,body:CredentialCreate):
    try:
        token=_store().issue_credential(tenant_id,application_id,body.principal_id,
                                        body.capabilities,body.ttl_seconds)
        return {"credential":token,"shown_once":True,"warning":"Store this secret securely; it cannot be retrieved again."}
    except (AuthorizationError,ValueError) as exc:
        raise HTTPException(400,str(exc))

@router.delete("/credentials/{credential_id}",dependencies=[Depends(require_owner)])
def revoke_credential(credential_id:str):
    if not _store().revoke_credential(credential_id):
        raise HTTPException(404,"Active credential not found")
    return {"credential_id":credential_id,"revoked":True}

@router.get("/identity")
def identity(identity=Depends(require_application)):
    return {"credential_id":identity.credential_id,"tenant_id":identity.tenant_id,
            "application_id":identity.application_id,"principal_id":identity.principal_id,
            "capabilities":sorted(identity.capabilities),"policy_version":identity.policy_version}

@router.get("/memories")
def list_memories(limit:int=100,identity=Depends(require_application)):
    try:
        return {"data":_store().list_memories(identity,limit)}
    except AuthorizationError as exc:
        raise HTTPException(403,str(exc))

@router.post("/memories",status_code=201)
def save_memory(body:MemoryCreate,identity=Depends(require_application)):
    try:
        memory_id=_store().save_memory(identity,body.content,body.category)
        return {"memory_id":memory_id,"stored":True}
    except AuthorizationError as exc:
        raise HTTPException(403,str(exc))
    except ValueError as exc:
        raise HTTPException(422,str(exc))

@router.post("/memory-sharing-grants",status_code=201)
def create_memory_share(body:MemoryShareCreate,identity=Depends(require_application)):
    try:
        grant_id=_store().share_memory(identity,body.destination_application_id,
                                       body.categories,body.purpose,body.ttl_seconds)
        return {"grant_id":grant_id,"status":"active"}
    except AuthorizationError as exc:
        raise HTTPException(403,str(exc))
    except ValueError as exc:
        raise HTTPException(422,str(exc))

@router.delete("/memory-sharing-grants/{grant_id}")
def revoke_memory_share(grant_id:str,identity=Depends(require_application)):
    try:
        if not _store().revoke_memory_share(identity,grant_id):
            raise HTTPException(404,"Active grant not found")
        return {"grant_id":grant_id,"revoked":True}
    except AuthorizationError as exc:
        raise HTTPException(403,str(exc))

@router.get("/shared-memories/{source_application_id}")
def read_shared_memories(source_application_id:str,identity=Depends(require_application)):
    try:
        return {"data":_store().shared_memories(identity,source_application_id)}
    except AuthorizationError as exc:
        raise HTTPException(403,str(exc))
