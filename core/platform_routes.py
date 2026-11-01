"""Scoped platform API for tenant/application credentials and SPARK memory.

Legacy owner routes remain owner-only. This router is the first application-credential
surface; it never accepts caller-supplied tenant/app/principal scope.
"""
from __future__ import annotations
from dataclasses import asdict
import hmac
import os
from pathlib import Path
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
import asyncio
import json
import time
from pydantic import BaseModel, Field
from typing import Any, Callable
from core.concierge_runtime import ConciergeWorkflowStore, ConciergeError
from core.tenant_security import TenantSecurityStore, AuthorizationError
from core.platform_control_plane import PlatformControlPlane
from core.worker_identity import WorkerIdentityStore, WorkerIdentity

router=APIRouter(prefix="/v1/platform",tags=["platform-identity"])
_CONCIERGE_EXECUTORS: dict[str, Callable] = {}


def register_concierge_executor(provider_id: str, executor: Callable):
    """Register a reviewed server-side provider adapter; never exposed as an API."""
    if not provider_id or not callable(executor) or provider_id in _CONCIERGE_EXECUTORS:
        raise ValueError("Invalid or duplicate Concierge executor")
    _CONCIERGE_EXECUTORS[provider_id]=executor


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

class TaskCreate(BaseModel):
    agent_id:str=Field(min_length=1,max_length=64)
    required_capabilities:list[str]=Field(default_factory=list,max_length=20)
    payload:dict=Field(default_factory=dict)

class TaskComplete(BaseModel):
    worker_id:str=Field(min_length=1,max_length=128)
    status:str="succeeded"
    result:dict=Field(default_factory=dict)

class ConciergePlan(BaseModel):
    action:dict
    ttl_seconds:int=Field(default=900,ge=60,le=3600)

class ConciergeConfirmation(BaseModel):
    action_fingerprint:str=Field(min_length=64,max_length=64)

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


@router.post("/agent-tasks",status_code=202)
def create_scoped_agent_task(body:TaskCreate,identity=Depends(require_application)):
    try:
        task_id=_store().create_scoped_task(identity,body.agent_id,body.required_capabilities,body.payload)
        return {"task_id":task_id,"status":"queued","tenant_scoped":True}
    except AuthorizationError as exc:
        raise HTTPException(403,str(exc))
    except ValueError as exc:
        raise HTTPException(422,str(exc))

@router.post("/agent-tasks/{task_id}/claim")
def claim_scoped_agent_task(task_id:str,worker_id:str,identity=Depends(require_application)):
    try:
        return _store().claim_scoped_task(identity,task_id,worker_id)
    except AuthorizationError as exc:
        raise HTTPException(404,str(exc))

@router.post("/agent-tasks/{task_id}/complete")
def complete_scoped_agent_task(task_id:str,body:TaskComplete,identity=Depends(require_application)):
    try:
        if not _store().complete_scoped_task(identity,task_id,body.worker_id,body.result,body.status):
            raise HTTPException(404,"Running task not found in this application scope")
        return {"task_id":task_id,"status":body.status}
    except AuthorizationError as exc:
        raise HTTPException(403,str(exc))
    except ValueError as exc:
        raise HTTPException(422,str(exc))

@router.get("/agent-tasks/{task_id}")
def get_scoped_agent_task(task_id:str,identity=Depends(require_application)):
    task=_store().get_scoped_task(identity,task_id)
    if not task:
        raise HTTPException(404,"Task not found")
    return task

@router.post("/concierge/workflows",status_code=201)
def plan_concierge_workflow(body:ConciergePlan,identity=Depends(require_application)):
    if "concierge.workflow.plan" not in identity.capabilities:
        raise HTTPException(403,"Concierge planning capability is not granted")
    try:
        result=ConciergeWorkflowStore(os.environ.get("ORACLE_ARC_DB_PATH","data/oracle_arc.sqlite3")).plan(
            identity,body.action,body.ttl_seconds)
        return result
    except ConciergeError as exc:
        raise HTTPException(422,str(exc))

@router.post("/concierge/workflows/{workflow_id}/confirm")
def confirm_concierge_workflow(workflow_id:str,body:ConciergeConfirmation,
                               identity=Depends(require_application)):
    if "concierge.action.execute" not in identity.capabilities:
        raise HTTPException(403,"Consequential Concierge execution is not granted")
    database=os.environ.get("ORACLE_ARC_DB_PATH","data/oracle_arc.sqlite3")
    store=ConciergeWorkflowStore(database)
    # Resolve the executor from a server-side allowlist, never from request input.
    try:
        import sqlite3, json
        with sqlite3.connect(database) as db:
            row=db.execute("SELECT action_json FROM concierge_workflows WHERE workflow_id=? AND tenant_id=? AND application_id=? AND principal_id=?",
                           (workflow_id,identity.tenant_id,identity.application_id,identity.principal_id)).fetchone()
        if not row:
            raise HTTPException(404,"Workflow not found")
        action=json.loads(row[0])
        executor=_CONCIERGE_EXECUTORS.get(action.get("provider"))
        if executor is None:
            raise HTTPException(503,"No reviewed Concierge provider adapter is configured; no action was performed")
        return store.confirm_and_execute(identity,workflow_id,body.action_fingerprint,executor)
    except ConciergeError as exc:
        raise HTTPException(409,str(exc))


# Shared metadata/execution control plane. This does not dynamically import or execute
# application-supplied code; a separately trusted worker must host approved runtimes.
def _control_plane() -> PlatformControlPlane:
    return PlatformControlPlane(os.environ.get("ORACLE_ARC_DB_PATH", "data/oracle_arc.sqlite3"))


def _worker_store() -> WorkerIdentityStore:
    # Ensure tenant/application tables exist before creating the worker foreign keys.
    _store()
    return WorkerIdentityStore(os.environ.get("ORACLE_ARC_DB_PATH", "data/oracle_arc.sqlite3"))


def require_worker(authorization: str | None = Header(default=None)) -> WorkerIdentity:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Worker credential required")
    try:
        return _worker_store().authenticate(token)
    except PermissionError:
        raise HTTPException(401, "Invalid, expired or revoked worker credential")


class WorkerIssue(BaseModel):
    capabilities: list[str] = Field(min_length=1, max_length=8)
    ttl_seconds: int = Field(default=86400, ge=60, le=2592000)


class WorkerClaim(BaseModel):
    lease_seconds: int = Field(default=60, ge=5, le=900)


class WorkerHeartbeat(BaseModel):
    lease_seconds: int = Field(default=60, ge=5, le=900)


class WorkerResult(BaseModel):
    output: dict[str, Any] = Field(default_factory=dict)


class WorkerFailure(BaseModel):
    error_code: str = Field(pattern=r"^[a-z0-9_.-]{1,80}$")
    retryable: bool = True


@router.post("/tenants/{tenant_id}/applications/{application_id}/workers", status_code=201,
             dependencies=[Depends(require_owner)])
def issue_worker(tenant_id: str, application_id: str, body: WorkerIssue):
    try:
        worker_id, token = _worker_store().issue(
            tenant_id, application_id, body.capabilities, body.ttl_seconds)
        return {"worker_id": worker_id, "credential": token, "shown_once": True}
    except (ValueError, LookupError) as exc:
        raise HTTPException(422, str(exc))


@router.delete("/workers/{worker_id}", dependencies=[Depends(require_owner)])
def revoke_worker(worker_id: str):
    if not _worker_store().revoke(worker_id):
        raise HTTPException(404, "Active worker not found")
    return {"worker_id": worker_id, "revoked": True}


@router.post("/worker/executions/claim")
def worker_claim(body: WorkerClaim, worker: WorkerIdentity = Depends(require_worker)):
    try:
        _worker_store().validate(worker, "execution.claim")
        execution = _control_plane().claim_execution(
            worker.worker_id, body.lease_seconds, worker.tenant_id, worker.application_id)
        return {"execution": asdict(execution) if execution else None}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/worker/executions/{execution_id}/heartbeat")
def worker_heartbeat(execution_id: str, body: WorkerHeartbeat,
                     worker: WorkerIdentity = Depends(require_worker)):
    try:
        _worker_store().validate(worker, "execution.heartbeat")
        ok = _control_plane().heartbeat_execution(execution_id, worker.worker_id, body.lease_seconds)
        if not ok:
            raise HTTPException(409, "Execution lease is no longer owned or has expired")
        return {"execution_id": execution_id, "lease_extended": True}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@router.post("/worker/executions/{execution_id}/complete")
def worker_complete(execution_id: str, body: WorkerResult,
                    worker: WorkerIdentity = Depends(require_worker)):
    try:
        _worker_store().validate(worker, "execution.complete")
        ok = _control_plane().complete_execution(execution_id, worker.worker_id, body.output)
        if not ok:
            raise HTTPException(409, "Execution lease is no longer owned or has expired")
        return {"execution_id": execution_id, "status": "succeeded"}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/worker/executions/{execution_id}/fail")
def worker_fail(execution_id: str, body: WorkerFailure,
                worker: WorkerIdentity = Depends(require_worker)):
    try:
        _worker_store().validate(worker, "execution.fail")
        ok = _control_plane().fail_execution(
            execution_id, worker.worker_id, body.error_code, body.retryable)
        if not ok:
            raise HTTPException(409, "Execution lease is no longer owned or has expired")
        return {"execution_id": execution_id, "status": "failure_recorded"}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


class AgentVersionCreate(BaseModel):
    agent_id: str = Field(min_length=2, max_length=64)
    version: str = Field(min_length=5, max_length=80)
    manifest: dict[str, Any]


class ModelRouteCreate(BaseModel):
    route_id: str = Field(min_length=2, max_length=64)
    provider_id: str = Field(min_length=2, max_length=64)
    model_id: str = Field(min_length=1, max_length=256)
    data_classifications: list[str] = Field(min_length=1, max_length=5)
    regions: list[str] = Field(min_length=1, max_length=10)


class ApplicationQuotaCreate(BaseModel):
    window_seconds: int = Field(ge=1, le=86400)
    max_executions: int = Field(ge=1, le=1000000)
    max_concurrent: int = Field(ge=1, le=10000)
    max_input_bytes: int = Field(ge=1, le=10000000)


class ExecutionCreate(BaseModel):
    agent_id: str = Field(min_length=2, max_length=64)
    agent_version: str = Field(min_length=5, max_length=80)
    route_id: str = Field(min_length=2, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    classification: str = "private"
    region: str = "local"
    max_attempts: int = Field(default=3, ge=1, le=10)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


@router.post("/agents/versions", status_code=201)
def register_agent_version(body: AgentVersionCreate, identity=Depends(require_application)):
    try:
        result = _control_plane().register_agent(identity, body.agent_id, body.version, body.manifest)
        return asdict(result)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except LookupError as exc:
        raise HTTPException(409, str(exc))


@router.get("/agents/{agent_id}/versions/{version}")
def read_agent_version(agent_id: str, version: str, identity=Depends(require_application)):
    try:
        return asdict(_control_plane().get_agent(identity, agent_id, version))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@router.delete("/agents/{agent_id}/versions/{version}")
def disable_agent_version(agent_id: str, version: str, identity=Depends(require_application)):
    try:
        if not _control_plane().disable_agent_version(identity, agent_id, version):
            raise HTTPException(404, "Agent version not found")
        return {"agent_id": agent_id, "version": version, "status": "disabled"}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@router.put("/model-routes/{route_id}")
def configure_model_route(route_id: str, body: ModelRouteCreate,
                           identity=Depends(require_application)):
    if route_id != body.route_id:
        raise HTTPException(422, "Route ID in path and body must match")
    try:
        _control_plane().configure_model_route(
            identity, body.route_id, body.provider_id, body.model_id,
            body.data_classifications, body.regions)
        return {"route_id": route_id, "status": "enabled"}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.put("/quotas")
def configure_application_quota(body: ApplicationQuotaCreate,
                                 identity=Depends(require_application)):
    try:
        _control_plane().set_quota(
            identity, window_seconds=body.window_seconds,
            max_executions=body.max_executions, max_concurrent=body.max_concurrent,
            max_input_bytes=body.max_input_bytes)
        return {"application_id": identity.application_id, "quota": body.dict()}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/executions", status_code=202)
def submit_platform_execution(body: ExecutionCreate,
                              identity=Depends(require_application)):
    try:
        execution_id = _control_plane().submit_execution(
            identity, body.agent_id, body.agent_version, body.route_id,
            body.payload, body.classification, body.region,
            body.max_attempts, body.idempotency_key)
        return {"execution_id": execution_id, "status": "queued"}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except LookupError as exc:
        raise HTTPException(409, str(exc))


@router.get("/executions/{execution_id}")
def read_platform_execution(execution_id: str, identity=Depends(require_application)):
    try:
        return asdict(_control_plane().get_execution(identity, execution_id))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@router.post("/executions/{execution_id}/usage", status_code=201)
def record_platform_usage(execution_id: str, metric: str, quantity: int,
                          identity=Depends(require_application)):
    try:
        _control_plane().record_usage(identity, execution_id, metric, quantity)
        return {"execution_id": execution_id, "metric": metric, "quantity": quantity}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/usage")
def read_platform_usage(since: int = 0, identity=Depends(require_application)):
    try:
        return {"application_id": identity.application_id,
                "totals": _control_plane().usage_summary(identity, since)}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/executions/{execution_id}/cancel")
def cancel_platform_execution(execution_id: str, identity=Depends(require_application)):
    try:
        if not _control_plane().cancel_execution(identity, execution_id):
            raise HTTPException(409, "Execution is not cancellable in its current state")
        return {"execution_id": execution_id, "status": "cancelled"}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


# Read-only console collections. Every query is constrained by the authenticated
# tenant, application and principal; caller-supplied scope is never trusted.
import sqlite3 as _sqlite3
import json as _json

@router.get("/agents")
def list_platform_agents(identity=Depends(require_application)):
    if "agent.read" not in identity.capabilities:
        raise HTTPException(403,"Agent read capability is not granted")
    cp=_control_plane()
    with _sqlite3.connect(cp.database_path) as db:
        db.row_factory=_sqlite3.Row
        rows=db.execute("""SELECT tenant_id,application_id,agent_id,version,manifest_json,manifest_digest
            FROM arc_agent_versions WHERE tenant_id=? AND application_id=? AND status='active'
            ORDER BY agent_id,created_at DESC""",(identity.tenant_id,identity.application_id)).fetchall()
    return {"data":[{"tenant_id":x["tenant_id"],"application_id":x["application_id"],
        "agent_id":x["agent_id"],"version":x["version"],"manifest":_json.loads(x["manifest_json"]),
        "manifest_digest":x["manifest_digest"]} for x in rows]}

@router.get("/model-routes")
def list_platform_model_routes(identity=Depends(require_application)):
    if "model.route.manage" not in identity.capabilities and "model.route.use" not in identity.capabilities:
        raise HTTPException(403,"Model route read capability is not granted")
    cp=_control_plane()
    with _sqlite3.connect(cp.database_path) as db:
        db.row_factory=_sqlite3.Row
        rows=db.execute("""SELECT route_id,provider_id,model_id,data_classifications_json,regions_json
            FROM arc_model_routes WHERE tenant_id=? AND application_id=? AND enabled=1 ORDER BY route_id""",
            (identity.tenant_id,identity.application_id)).fetchall()
    return {"data":[{"route_id":x["route_id"],"provider_id":x["provider_id"],"model_id":x["model_id"],
        "data_classifications":_json.loads(x["data_classifications_json"]),
        "regions":_json.loads(x["regions_json"])} for x in rows]}

@router.get("/quotas")
def read_application_quota(identity=Depends(require_application)):
    if "quota.read" not in identity.capabilities and "quota.manage" not in identity.capabilities:
        raise HTTPException(403,"Quota read capability is not granted")
    cp=_control_plane()
    with _sqlite3.connect(cp.database_path) as db:
        db.row_factory=_sqlite3.Row
        row=db.execute("""SELECT window_seconds,max_executions,max_concurrent,max_input_bytes
            FROM arc_app_quotas WHERE tenant_id=? AND application_id=?""",
            (identity.tenant_id,identity.application_id)).fetchone()
    return {"application_id":identity.application_id,"quota":dict(row) if row else None}

@router.get("/executions")
def list_platform_executions(limit:int=50,identity=Depends(require_application)):
    if "agent.execution.read" not in identity.capabilities:
        raise HTTPException(403,"Execution read capability is not granted")
    if not 1<=limit<=100: raise HTTPException(422,"Limit must be between 1 and 100")
    cp=_control_plane()
    with _sqlite3.connect(cp.database_path) as db:
        db.row_factory=_sqlite3.Row
        rows=db.execute("""SELECT * FROM arc_executions WHERE tenant_id=? AND application_id=?
            AND principal_id=? ORDER BY created_at DESC LIMIT ?""",
            (identity.tenant_id,identity.application_id,identity.principal_id,limit)).fetchall()
    return {"data":[asdict(cp._execution(x)) for x in rows]}

@router.get("/executions/events")
async def stream_platform_execution_events(after: int = 0,
        authorization: str | None = Header(default=None)):
    """Stream durable event-log updates; every reconnect revalidates the bearer credential."""
    if not isinstance(after, int) or after < 0:
        raise HTTPException(422, "Event cursor must be a non-negative integer")
    identity = require_application(authorization)
    if "agent.execution.read" not in identity.capabilities:
        raise HTTPException(403, "Execution read capability is not granted")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Application credential required")
    cp = _control_plane()

    async def events():
        cursor = after
        started = time.monotonic()
        last_heartbeat = started
        last_auth_check = started
        yield "retry: 2000\n\n"
        # Netlify and common reverse proxies impose bounded response lifetimes.
        # The client reconnects using the last durable event ID.
        while time.monotonic() - started < 50:
            if time.monotonic() - last_auth_check >= 10:
                try:
                    live_identity = _store().authenticate(token)
                except AuthorizationError:
                    yield "event: auth.expired\ndata: {\"reason\":\"credential_expired_or_revoked\"}\n\n"
                    return
                if (live_identity.tenant_id != identity.tenant_id
                        or live_identity.application_id != identity.application_id
                        or live_identity.principal_id != identity.principal_id):
                    yield "event: auth.expired\ndata: {\"reason\":\"identity_scope_changed\"}\n\n"
                    return
                last_auth_check = time.monotonic()
            try:
                batch = cp.list_execution_events(identity, cursor, 100)
            except (PermissionError, ValueError):
                yield "event: stream.error\ndata: {\"reason\":\"execution_event_access_denied\"}\n\n"
                return
            for item in batch:
                cursor = item["event_id"]
                yield (f"id: {cursor}\nevent: execution\ndata: "
                       + json.dumps(item, separators=(",", ":"), ensure_ascii=False) + "\n\n")
            now = time.monotonic()
            if not batch and now - last_heartbeat >= 15:
                yield ": keepalive\n\n"
                last_heartbeat = now
            await asyncio.sleep(0.75)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-store, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })

