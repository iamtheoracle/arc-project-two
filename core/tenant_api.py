"""Private owner-provisioned tenant API; customer routes use resolved application identity."""
from __future__ import annotations
import hmac
import os
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from core.tenant_identity import TenantIdentityStore, RequestIdentity
from core.tenant_store import TenantStore
from core.privacy_gateway import InferencePolicy, PrivacyAwareModelGateway

router=APIRouter(prefix="/v1/tenants",tags=["tenant-platform"])

_gateway_instance = None

def _gateway():
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = PrivacyAwareModelGateway()
    return _gateway_instance



def _database_path():
    return os.environ.get("ORACLE_ARC_DB_PATH","data/oracle_arc.sqlite3")


def _identity_database_path():
    # The legacy /v1/tenants identity schema predates TenantSecurityStore and is not
    # column-compatible with the Project One /v1/platform schema. Keep it in a
    # separate SQLite file so enabling both routers cannot corrupt either identity plane.
    configured=os.environ.get("ORACLE_ARC_TENANT_IDENTITY_DB_PATH")
    if configured:
        return configured
    base,extension=os.path.splitext(_database_path())
    return base+"_tenant_identity"+(extension or ".sqlite3")


def _identity_store():
    return TenantIdentityStore(_identity_database_path())


def _tenant_store():
    return TenantStore(_identity_database_path())


def _owner(authorization: str|None=Header(default=None)):
    expected=os.environ.get("ORACLE_ARC_API_KEY","").strip()
    scheme,_,token=(authorization or "").partition(" ")
    if not expected or len(expected)<32:
        raise HTTPException(503,"Owner provisioning secret is not configured")
    if scheme.lower()!="bearer" or not hmac.compare_digest(token,expected):
        raise HTTPException(401,"Owner authentication required")


def _application_identity(authorization: str|None=Header(default=None))->RequestIdentity:
    scheme,_,token=(authorization or "").partition(" ")
    if scheme.lower()!="bearer" or not token:
        raise HTTPException(401,"Application credential required")
    try:
        return _identity_store().authenticate(token)
    except PermissionError:
        raise HTTPException(401,"Application credential is invalid, expired or revoked")


class TenantProvision(BaseModel):
    tenant_name:str=Field(min_length=1,max_length=160)
    application_name:str=Field(min_length=1,max_length=160)
    principal_id:str=Field(min_length=1,max_length=160)
    capabilities:list[str]=Field(min_length=1,max_length=40)
    ttl_seconds:int=Field(default=86400,ge=60,le=31536000)


class ApplicationProvision(BaseModel):
    tenant_id:str=Field(min_length=5,max_length=100)
    application_name:str=Field(min_length=1,max_length=160)
    principal_id:str=Field(min_length=1,max_length=160)
    capabilities:list[str]=Field(min_length=1,max_length=40)
    ttl_seconds:int=Field(default=86400,ge=60,le=31536000)


class ConversationCreate(BaseModel):
    title:str=Field(default="",max_length=160)


class MessageCreate(BaseModel):
    role:str
    content:str=Field(min_length=1,max_length=100000)


class MemoryCreate(BaseModel):
    content:str=Field(min_length=1,max_length=20000)
    category:str=Field(default="general",max_length=40)
    tags:list[str]=Field(default_factory=list,max_length=20)


class MemoryUpdate(BaseModel):
    content:str=Field(min_length=1,max_length=20000)
    category:str=Field(default="general",max_length=40)
    tags:list[str]=Field(default_factory=list,max_length=20)


def build_inference_policy(identity: RequestIdentity) -> InferencePolicy:
    """Build trusted provider policy only from the authenticated application identity."""
    capabilities = set(identity.capabilities)
    allowed = ["ollama"] if "inference.provider.ollama" in capabilities else []
    remote_names = {
        name for name in ("openrouter", "groq", "gemini", "claude")
        if "inference.remote." + name in capabilities
    }
    remote_ok = (
        "inference.remote.allow" in capabilities
        and "inference.remote.public" in capabilities
        and "inference.remote.region.unspecified" in capabilities
    )
    if remote_ok:
        allowed.extend(sorted(remote_names))
    return InferencePolicy(
        identity.tenant_id,
        identity.application_id,
        tuple(allowed),
        data_classification="public" if remote_ok else "private",
        allow_remote=remote_ok,
        allowed_regions=("local", "unspecified") if remote_ok else ("local",),
        policy_version=identity.policy_version,
    )

class InferenceRequest(BaseModel):
    messages:list[dict]=Field(min_length=1,max_length=100)
    provider_id:str=Field(default="ollama",max_length=40)
    temperature:float=Field(default=0.7,ge=0,le=2)


@router.post("/provision",dependencies=[Depends(_owner)],status_code=201)
def provision_tenant(request:TenantProvision):
    try:
        return _identity_store().provision(request.tenant_name,request.application_name,
            request.principal_id,request.capabilities,request.ttl_seconds)
    except (ValueError,LookupError) as exc:
        raise HTTPException(422,str(exc))


@router.post("/applications",dependencies=[Depends(_owner)],status_code=201)
def provision_application(request:ApplicationProvision):
    try:
        return _identity_store().provision_application(request.tenant_id,request.application_name,
            request.principal_id,request.capabilities,request.ttl_seconds)
    except (ValueError,LookupError) as exc:
        raise HTTPException(422,str(exc))


@router.get("/identity")
def current_identity(identity:RequestIdentity=Depends(_application_identity)):
    return {"tenant_id":identity.tenant_id,"application_id":identity.application_id,
        "principal_id":identity.principal_id,"capabilities":list(identity.capabilities),
        "policy_version":identity.policy_version,"expires_at":identity.expires_at}


@router.post("/conversations",status_code=201)
def create_conversation(request:ConversationCreate,identity:RequestIdentity=Depends(_application_identity)):
    try:return {"conversation_id":_tenant_store().create_conversation(identity,request.title)}
    except PermissionError as exc:raise HTTPException(403,str(exc))


@router.get("/conversations/{conversation_id}/messages")
def get_messages(conversation_id:str,identity:RequestIdentity=Depends(_application_identity)):
    try:return {"data":_tenant_store().get_messages(identity,conversation_id)}
    except PermissionError as exc:raise HTTPException(403,str(exc))
    except LookupError:raise HTTPException(404,"Conversation not found")


@router.post("/conversations/{conversation_id}/messages",status_code=201)
def add_message(conversation_id:str,request:MessageCreate,identity:RequestIdentity=Depends(_application_identity)):
    try:return {"message_id":_tenant_store().add_message(identity,conversation_id,request.role,request.content)}
    except PermissionError as exc:raise HTTPException(403,str(exc))
    except LookupError:raise HTTPException(404,"Conversation not found")
    except ValueError as exc:raise HTTPException(422,str(exc))


@router.post("/memories",status_code=201)
def save_memory(request:MemoryCreate,identity:RequestIdentity=Depends(_application_identity)):
    try:return {"memory_id":_tenant_store().save_memory(identity,request.content,request.category,request.tags)}
    except PermissionError as exc:raise HTTPException(403,str(exc))
    except ValueError as exc:raise HTTPException(422,str(exc))


@router.post("/inference")
def tenant_inference(request:InferenceRequest,identity:RequestIdentity=Depends(_application_identity)):
    if "inference.chat" not in identity.capabilities:
        raise HTTPException(403,"Inference capability is not granted")
    policy=build_inference_policy(identity)
    try:
        if any(not isinstance(item,dict) or item.get("role") not in {"system","user","assistant"}
               or not isinstance(item.get("content"),str) or not item["content"]
               for item in request.messages):
            raise HTTPException(422,"Inference messages require supported roles and non-empty text")
        result=_gateway().chat(policy,os.environ.get("ORACLE_ARC_MODEL","qwen2.5:7b"),
            request.messages,temperature=request.temperature,provider_id=request.provider_id)
        return {"data":result,"tenant_id":identity.tenant_id,"application_id":identity.application_id,
                "policy_version":identity.policy_version}
    except PermissionError as exc:
        raise HTTPException(403,str(exc))
    except Exception:
        raise HTTPException(503,"The authorized inference provider is unavailable")

@router.get("/memories")
def list_memories(identity:RequestIdentity=Depends(_application_identity)):
    try:return {"data":_tenant_store().list_memories(identity)}
    except PermissionError as exc:raise HTTPException(403,str(exc))


@router.put("/memories/{memory_id}")
def update_memory(memory_id:str,request:MemoryUpdate,identity:RequestIdentity=Depends(_application_identity)):
    try:
        if not _tenant_store().update_memory(identity,memory_id,request.content,request.category,request.tags):
            raise HTTPException(404,"Memory not found")
        return {"memory_id":memory_id,"updated":True}
    except PermissionError as exc:raise HTTPException(403,str(exc))
    except ValueError as exc:raise HTTPException(422,str(exc))


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id:str,identity:RequestIdentity=Depends(_application_identity)):
    try:
        if not _tenant_store().delete_memory(identity,memory_id):
            raise HTTPException(404,"Memory not found")
        return {"memory_id":memory_id,"deleted":True}
    except PermissionError as exc:raise HTTPException(403,str(exc))

# Owner-only tool grants. These are separate from an application's own capabilities:
# an application cannot grant itself tools by editing its agent manifest.
import hmac as _hmac
from fastapi import Query as _Query
from pydantic import BaseModel as _BaseModel, Field as _Field
from core.tool_grants import ToolGrantStore
from core.platform_tool_registry import PLATFORM_TOOL_IDS

owner_tools_router=APIRouter(prefix="/owner/tool-grants",tags=["owner-tool-governance"])

def _tool_grant_store():
    return ToolGrantStore(_database_path())

def _require_owner_tool_admin(authorization: str|None=Header(default=None)):
    expected=os.environ.get("ORACLE_ARC_API_KEY","").strip()
    scheme,_,token=(authorization or "").partition(" ")
    if not expected or len(expected)<32 or expected.startswith("replace-with-"):
        raise HTTPException(503,"Owner control-plane secret is not configured")
    if scheme.lower()!="bearer" or not token or not _hmac.compare_digest(token,expected):
        raise HTTPException(401,"Owner authentication required")

class OwnerToolGrantCreate(_BaseModel):
    tenant_id:str=_Field(min_length=5,max_length=100)
    application_id:str=_Field(min_length=5,max_length=100)
    tool_id:str=_Field(min_length=2,max_length=64)

@owner_tools_router.get("",dependencies=[Depends(_require_owner_tool_admin)])
def list_owner_tool_grants(tenant_id:str|None=_Query(default=None,min_length=5,max_length=100),
                           application_id:str|None=_Query(default=None,min_length=5,max_length=100)):
    if (tenant_id is None)!=(application_id is None):
        raise HTTPException(422,"Tenant and application filters must be supplied together")
    return {"data":_tool_grant_store().list(tenant_id,application_id)}

@owner_tools_router.post("",status_code=201,dependencies=[Depends(_require_owner_tool_admin)])
def create_owner_tool_grant(body:OwnerToolGrantCreate):
    if body.tool_id not in PLATFORM_TOOL_IDS:
        raise HTTPException(422,"Tool is not present in the trusted platform registry")
    actor="owner-control-plane"
    try:return _tool_grant_store().grant(body.tenant_id,body.application_id,body.tool_id,actor)
    except LookupError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:raise HTTPException(409,str(exc))

@owner_tools_router.delete("/{grant_id}",dependencies=[Depends(_require_owner_tool_admin)])
def revoke_owner_tool_grant(grant_id:str):
    if not _tool_grant_store().revoke(grant_id,"owner-control-plane"):
        raise HTTPException(404,"Active tool grant not found")
    return {"grant_id":grant_id,"revoked":True}

router.include_router(owner_tools_router)
