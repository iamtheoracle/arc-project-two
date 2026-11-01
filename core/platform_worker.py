"""Trusted Oracle Arc platform worker runtime.

This runner executes only registered, active agent versions using the model provider
and model pinned to the queued execution. It deliberately exposes no arbitrary tool
execution; tool calls require a separately reviewed scoped tool broker.
"""
from __future__ import annotations
import json
import sqlite3
from typing import Any
from core.model_gateway import ModelGateway
from core.platform_control_plane import PlatformControlPlane
from core.worker_identity import WorkerIdentityStore


class PlatformWorker:
    def __init__(self, database_path: str, worker_token: str):
        self.database_path=database_path
        self.identities=WorkerIdentityStore(database_path)
        self.identity=self.identities.authenticate(worker_token)
        self.control=PlatformControlPlane(database_path)

    def _execution_context(self, execution_id: str, worker_id: str) -> tuple[dict[str,Any],dict[str,Any]]:
        with sqlite3.connect(self.database_path) as db:
            db.row_factory=sqlite3.Row
            row=db.execute("""SELECT e.*,a.manifest_json,a.status agent_status,
                r.enabled route_enabled,r.provider_id current_provider,r.model_id current_model,
                r.data_classifications_json,r.regions_json
                FROM arc_executions e
                JOIN arc_agent_versions a ON a.tenant_id=e.tenant_id
                  AND a.application_id=e.application_id AND a.agent_id=e.agent_id
                  AND a.version=e.agent_version
                JOIN arc_model_routes r ON r.tenant_id=e.tenant_id
                  AND r.application_id=e.application_id AND r.route_id=e.route_id
                WHERE e.execution_id=? AND e.tenant_id=? AND e.application_id=?
                  AND e.status='running' AND e.lease_owner=? AND e.lease_expires_at>strftime('%s','now')""",
                (execution_id,self.identity.tenant_id,self.identity.application_id,worker_id)).fetchone()
        if row is None:
            raise PermissionError("Execution lease or application scope is no longer valid")
        if row["agent_status"]!="active" or not row["route_enabled"]:
            raise PermissionError("Agent version or model route is no longer active")
        if row["current_provider"]!=row["model_provider"] or row["current_model"]!=row["model_id"]:
            raise PermissionError("Model route changed after execution submission")
        manifest=json.loads(row["manifest_json"])
        route={"provider_id":row["model_provider"],"model_id":row["model_id"],
               "classifications":json.loads(row["data_classifications_json"]),
               "regions":json.loads(row["regions_json"])}
        if not set(manifest["required_capabilities"]).issubset(self.identity.capabilities):
            raise PermissionError("Worker lacks the agent's required capabilities")
        if not set(manifest["allowed_tools"]).issubset(self.identity.capabilities):
            raise PermissionError("Worker lacks the agent's declared tool grants")
        return dict(row),{"manifest":manifest,"route":route}

    @staticmethod
    def _messages(payload: dict[str,Any], manifest: dict[str,Any]) -> list[dict[str,str]]:
        messages=payload.get("messages")
        if messages is None:
            prompt=payload.get("prompt") or payload.get("query")
            if not isinstance(prompt,str) or not prompt.strip():
                raise ValueError("Execution payload must contain messages or a prompt/query string")
            messages=[{"role":"user","content":prompt}]
        if not isinstance(messages,list) or not 1<=len(messages)<=100:
            raise ValueError("Execution messages must be a list containing 1 to 100 messages")
        safe=[]
        for item in messages:
            if not isinstance(item,dict) or item.get("role") not in {"user","assistant"}:
                raise ValueError("Execution messages may contain only user and assistant roles")
            content=item.get("content")
            if not isinstance(content,str) or not content.strip() or len(content)>100000:
                raise ValueError("Execution message content is invalid")
            safe.append({"role":item["role"],"content":content})
        system=("You are "+manifest["display_name"]+". "+manifest["description"]+
                " Follow the user's request, state uncertainty, and never claim tools or actions "
                "were used unless a trusted tool result is supplied. No tools are available in this run.")
        return [{"role":"system","content":system}]+safe

    def run_once(self, lease_seconds: int=120) -> dict[str,Any] | None:
        self.identities.validate(self.identity,"execution.claim")
        execution=self.control.claim_execution(self.identity.worker_id,lease_seconds,
            self.identity.tenant_id,self.identity.application_id)
        if execution is None:
            return None
        try:
            self.identities.validate(self.identity,"execution.complete")
            row,context=self._execution_context(execution.execution_id,self.identity.worker_id)
            payload=json.loads(row["input_json"])
            messages=self._messages(payload,context["manifest"])
            gateway=ModelGateway(provider_id=context["route"]["provider_id"])
            response=gateway.chat(context["route"]["model_id"],messages,temperature=0.2)
            message=response.get("message",{}) if isinstance(response,dict) else {}
            output=message.get("content") if isinstance(message,dict) else None
            if not isinstance(output,str) or not output.strip():
                raise RuntimeError("model_empty_response")
            result={"content":output,"agent_id":execution.agent_id,
                    "agent_version":execution.agent_version,
                    "provider_id":context["route"]["provider_id"],
                    "model_id":context["route"]["model_id"]}
            if not self.control.complete_execution(execution.execution_id,self.identity.worker_id,result):
                raise RuntimeError("execution_lease_lost")
            return {"execution_id":execution.execution_id,"status":"succeeded","output":result}
        except Exception as exc:
            code=str(exc) if str(exc).replace("_","").replace("-","").isalnum() and len(str(exc))<=80 else "worker_execution_failed"
            self.control.fail_execution(execution.execution_id,self.identity.worker_id,code,retryable=True)
            raise
