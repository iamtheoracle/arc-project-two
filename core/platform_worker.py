"""Trusted Oracle Arc platform worker and permission-intersected tool lifecycle.

Workers claim only their own application queue. Model tool calls are exposed only when the
immutable agent manifest, live application-principal capability, live owner grant, and
worker credential all authorize the same reviewed tool. Tool handlers are server-registered;
agent-supplied code is never imported or evaluated.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from core.model_gateway import ModelGateway
from core.platform_control_plane import PlatformControlPlane
from core.platform_tool_registry import build_platform_tool_broker
from core.scoped_tool_broker import ScopedToolBroker, ToolContext
from core.tool_grants import ToolGrantStore
from core.worker_identity import WorkerIdentityStore


class PlatformWorker:
    def __init__(self, database_path: str, worker_token: str,
                 tool_broker: ScopedToolBroker | None = None):
        self.database_path = database_path
        self.identities = WorkerIdentityStore(database_path)
        self.identity = self.identities.authenticate(worker_token)
        self.control = PlatformControlPlane(database_path)
        self.tool_grants = ToolGrantStore(database_path)
        self.tool_broker = tool_broker or build_platform_tool_broker()
        self.identities.validate(self.identity, "execution.claim")
        self.identities.validate(self.identity, "execution.complete")

    def _execution_context(self, execution_id: str, worker_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        with sqlite3.connect(self.database_path, timeout=15) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=15000")
            row = db.execute("""SELECT e.*,a.manifest_json,a.status agent_status,
                r.enabled route_enabled,r.provider_id current_provider,r.model_id current_model,
                r.data_classifications_json,r.regions_json
                FROM arc_executions e
                JOIN arc_agent_versions a ON a.tenant_id=e.tenant_id
                  AND a.application_id=e.application_id AND a.agent_id=e.agent_id
                  AND a.version=e.agent_version
                JOIN arc_model_routes r ON r.tenant_id=e.tenant_id
                  AND r.application_id=e.application_id AND r.route_id=e.route_id
                WHERE e.execution_id=? AND e.tenant_id=? AND e.application_id=?
                  AND e.status='running' AND e.lease_owner=? AND e.lease_expires_at>?""",
                (execution_id, self.identity.tenant_id, self.identity.application_id,
                 worker_id, int(time.time()))).fetchone()
        if row is None:
            raise PermissionError("Execution lease or application scope is no longer valid")
        if row["agent_status"] != "active" or not row["route_enabled"]:
            raise PermissionError("Agent version or model route is no longer active")
        if row["current_provider"] != row["model_provider"] or row["current_model"] != row["model_id"]:
            raise PermissionError("Model route changed after execution submission")
        manifest = json.loads(row["manifest_json"])
        classifications = json.loads(row["data_classifications_json"])
        regions = json.loads(row["regions_json"])
        if row["classification"] not in classifications or row["region"] not in regions:
            raise PermissionError("Model route no longer permits this classification or region")
        return dict(row), {
            "manifest": manifest,
            "route": {"provider_id": row["model_provider"], "model_id": row["model_id"]},
        }

    def _application_tool_capabilities(self, row: dict[str, Any]) -> set[str]:
        """Read current, unexpired principal capabilities; never trust a queued snapshot."""
        now = int(time.time())
        with sqlite3.connect(self.database_path, timeout=15) as db:
            rows = db.execute("""SELECT c.capabilities_json
                FROM arc_credentials c
                JOIN arc_tenants t ON t.tenant_id=c.tenant_id
                JOIN arc_applications a ON a.tenant_id=c.tenant_id AND a.application_id=c.application_id
                JOIN arc_principals p ON p.principal_id=c.principal_id
                WHERE c.tenant_id=? AND c.application_id=? AND c.principal_id=?
                  AND c.revoked_at IS NULL AND c.expires_at>? AND t.status='active'
                  AND a.status='active' AND p.status='active'""",
                (row["tenant_id"], row["application_id"], row["principal_id"], now)).fetchall()
        capabilities: set[str] = set()
        for item in rows:
            try:
                parsed = json.loads(item[0])
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, list):
                capabilities.update(x for x in parsed if isinstance(x, str))
        return capabilities

    def _effective_tool_policy(self, row: dict[str, Any],
                               manifest: dict[str, Any]) -> tuple[set[str], set[str], set[str], set[str]]:
        manifest_tools = set(manifest.get("allowed_tools", []))
        application_capabilities = self._application_tool_capabilities(row)
        application_grants = {
            tool_id for tool_id in manifest_tools
            if tool_id in application_capabilities
        }
        owner_policy = self.tool_grants.active_tool_ids(
            self.identity.tenant_id, self.identity.application_id
        )
        worker_capabilities = set(self.identity.capabilities)
        return manifest_tools, application_grants, owner_policy, worker_capabilities

    @staticmethod
    def _messages(payload: dict[str, Any], manifest: dict[str, Any]) -> list[dict[str, str]]:
        if not isinstance(payload, dict):
            raise ValueError("Execution payload must be an object")
        messages = payload.get("messages")
        if messages is None:
            prompt = payload.get("prompt") or payload.get("query")
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("Execution payload must contain messages or a prompt/query string")
            messages = [{"role": "user", "content": prompt}]
        if not isinstance(messages, list) or not 1 <= len(messages) <= 100:
            raise ValueError("Execution messages must contain 1 to 100 messages")
        safe = []
        for item in messages:
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                raise ValueError("Execution messages may contain only user and assistant roles")
            content = item.get("content")
            if not isinstance(content, str) or not content.strip() or len(content) > 100000:
                raise ValueError("Execution message content is invalid")
            safe.append({"role": item["role"], "content": content})
        system = (
            "You are " + manifest["display_name"] + ". " + manifest["description"]
            + " Follow the user's request and state uncertainty. You may use only tools "
            "explicitly supplied in this request. Never claim a tool or external action "
            "was used unless its trusted tool result appears in the conversation."
        )
        return [{"role": "system", "content": system}] + safe

    @staticmethod
    def _field(response: Any, key: str, default: Any = None) -> Any:
        if isinstance(response, dict):
            return response.get(key, default)
        return getattr(response, key, default)

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if callable(getattr(value, "model_dump", None)):
            result = value.model_dump()
            return result if isinstance(result, dict) else {}
        if callable(getattr(value, "dict", None)):
            result = value.dict()
            return result if isinstance(result, dict) else {}
        return {}

    @staticmethod
    def _tool_call(call: Any) -> tuple[str, dict[str, Any], str | None]:
        call_data = PlatformWorker._mapping(call)
        function = PlatformWorker._mapping(call_data.get("function"))
        name = function.get("name")
        call_id = call_data.get("id")
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError as exc:
                raise ValueError("Model returned invalid tool-call JSON") from exc
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise ValueError("Model returned an invalid tool call")
        if call_id is not None and (not isinstance(call_id, str) or len(call_id) > 128):
            raise ValueError("Model returned an invalid tool-call identifier")
        return name, arguments, call_id

    def _model_with_tools(self, gateway: ModelGateway, model: str,
                          messages: list[dict[str, Any]], execution_id: str,
                          worker_id: str) -> tuple[str, dict[str, int]]:
        usage: dict[str, int] = {}
        max_tool_rounds = 4
        total_tool_calls = 0
        for round_index in range(max_tool_rounds + 1):
            self.identities.validate(self.identity, "execution.complete")
            row, context = self._execution_context(execution_id, worker_id)
            manifest_tools, app_grants, owner_policy, worker_capabilities = (
                self._effective_tool_policy(row, context["manifest"])
            )
            schemas = self.tool_broker.schemas(
                manifest_tools=manifest_tools,
                application_grants=app_grants,
                owner_policy=owner_policy,
                worker_capabilities=worker_capabilities,
            )
            if manifest_tools and not schemas:
                raise PermissionError("No declared agent tools remain authorized by all four permission boundaries")
            if len(messages) > 100:
                raise ValueError("execution_message_history_limit_exceeded")
            response = gateway.chat(
                model, messages, tools=schemas or None, temperature=0.2
            )
            for metric, key in (("input_tokens", "prompt_eval_count"),
                                ("output_tokens", "eval_count")):
                quantity = self._field(response, key)
                if isinstance(quantity, int) and not isinstance(quantity, bool) and quantity >= 0:
                    usage[metric] = usage.get(metric, 0) + quantity

            message = self._field(response, "message", {})
            content = self._field(message, "content", "")
            if not isinstance(content, str):
                content = ""
            calls = self._field(message, "tool_calls", []) or []
            if not calls:
                if not content.strip():
                    raise RuntimeError("model_empty_response")
                return content, usage
            if round_index >= max_tool_rounds:
                raise RuntimeError("tool_call_round_limit_exceeded")

            if not isinstance(calls, (list, tuple)) or len(calls) > 8:
                raise ValueError("model_tool_call_batch_limit_exceeded")
            total_tool_calls += len(calls)
            if total_tool_calls > 16:
                raise ValueError("execution_tool_call_limit_exceeded")
            parsed_calls = []
            for call in calls:
                function_name, arguments, call_id = self._tool_call(call)
                tool_id = self.tool_broker.resolve_tool_id(function_name)
                if tool_id is None:
                    raise PermissionError("Model requested a function outside the trusted tool registry")
                parsed_calls.append((function_name, tool_id, arguments, call_id))
            normalized_calls = []
            for function_name, tool_id, arguments, call_id in parsed_calls:
                normalized = {
                    "type": "function",
                    "function": {"name": function_name, "arguments": arguments},
                }
                if call_id:
                    normalized["id"] = call_id
                normalized_calls.append(normalized)
            # The provider contract requires non-empty text, even for an assistant
            # message whose only content is a tool-call list.
            messages.append({
                "role": "assistant",
                "content": content if content.strip() else " ",
                "tool_calls": normalized_calls,
            })

            for function_name, tool_id, arguments, call_id in parsed_calls:
                # Refresh every boundary immediately before each consequential tool call.
                self.identities.validate(self.identity, "execution.complete")
                latest_row, latest_context = self._execution_context(execution_id, worker_id)
                manifest_tools, app_grants, owner_policy, worker_capabilities = (
                    self._effective_tool_policy(latest_row, latest_context["manifest"])
                )
                result = self.tool_broker.execute(
                    tool_id, arguments,
                    context=ToolContext(
                        tenant_id=latest_row["tenant_id"],
                        application_id=latest_row["application_id"],
                        execution_id=execution_id,
                        principal_id=latest_row["principal_id"],
                    ),
                    manifest_tools=manifest_tools,
                    application_grants=app_grants,
                    owner_policy=owner_policy,
                    worker_capabilities=worker_capabilities,
                )
                tool_message = {
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                }
                if call_id:
                    tool_message["tool_call_id"] = call_id
                messages.append(tool_message)
        raise RuntimeError("model_tool_loop_terminated_unexpectedly")

    def _heartbeat_loop(self, execution_id: str, lease_seconds: int,
                        stop: threading.Event, lost: threading.Event) -> None:
        if "execution.heartbeat" not in self.identity.capabilities:
            return
        interval = max(2, min(30, lease_seconds // 3))
        while not stop.wait(interval):
            try:
                self.identities.validate(self.identity, "execution.heartbeat")
                if not self.control.heartbeat_execution(
                    execution_id, self.identity.worker_id, lease_seconds
                ):
                    lost.set()
                    return
            except Exception:
                lost.set()
                return

    def run_once(self, lease_seconds: int = 120) -> dict[str, Any] | None:
        self.identities.validate(self.identity, "execution.claim")
        self.control.recover_expired_leases(
            self.identity.tenant_id, self.identity.application_id
        )
        execution = self.control.claim_execution(
            self.identity.worker_id, lease_seconds,
            self.identity.tenant_id, self.identity.application_id,
        )
        if execution is None:
            return None

        stop = threading.Event()
        lost = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(execution.execution_id, lease_seconds, stop, lost),
            name="arc-execution-heartbeat",
            daemon=True,
        )
        heartbeat.start()
        gateway: ModelGateway | None = None
        try:
            self.identities.validate(self.identity, "execution.complete")
            row, context = self._execution_context(execution.execution_id, self.identity.worker_id)
            payload = json.loads(row["input_json"])
            messages = self._messages(payload, context["manifest"])
            self.identities.validate(self.identity, "execution.complete")
            gateway = ModelGateway(provider_id=context["route"]["provider_id"])
            output_text, usage = self._model_with_tools(
                gateway, context["route"]["model_id"], messages,
                execution.execution_id, self.identity.worker_id,
            )
            result = {
                "content": output_text,
                "agent_id": execution.agent_id,
                "agent_version": execution.agent_version,
                "provider_id": context["route"]["provider_id"],
                "model_id": context["route"]["model_id"],
            }
            self.identities.validate(self.identity, "execution.complete")
            if lost.is_set():
                raise RuntimeError("execution_lease_lost")
            if not self.control.complete_execution_with_usage(
                execution.execution_id, self.identity.worker_id, result, usage
            ):
                raise RuntimeError("execution_lease_lost")
            return {"execution_id": execution.execution_id, "status": "succeeded",
                    "output": result, "usage": usage}
        except Exception as exc:
            policy_failure = isinstance(exc, (PermissionError, ValueError))
            raw_code = str(exc).lower().replace(" ", "_")
            code = raw_code if raw_code.replace("_", "").replace("-", "").isalnum() and len(raw_code) <= 80 else "worker_execution_failed"
            if not lost.is_set():
                try:
                    self.control.fail_execution(
                        execution.execution_id, self.identity.worker_id,
                        code, retryable=not policy_failure,
                    )
                except Exception:
                    pass
            raise
        finally:
            stop.set()
            heartbeat.join(timeout=2)
            if gateway is not None:
                try:
                    gateway.close()
                except Exception:
                    pass

    def run_forever(self, stop_event: threading.Event, poll_interval: float = 1.0,
                    lease_seconds: int = 120) -> None:
        if not isinstance(poll_interval, (int, float)) or not 0.1 <= poll_interval <= 60:
            raise ValueError("poll_interval must be between 0.1 and 60 seconds")
        while not stop_event.is_set():
            try:
                result = self.run_once(lease_seconds=lease_seconds)
                if result is None:
                    stop_event.wait(poll_interval)
            except Exception:
                stop_event.wait(min(5.0, max(poll_interval, 0.5)))


def main() -> None:
    import os
    import signal

    database_path = os.environ.get("ORACLE_ARC_DB_PATH", "data/oracle_arc.sqlite3")
    token = os.environ.get("ORACLE_ARC_WORKER_TOKEN")
    if not token:
        raise SystemExit("ORACLE_ARC_WORKER_TOKEN must be set in the worker service environment")
    poll_interval = float(os.environ.get("ORACLE_ARC_WORKER_POLL_SECONDS", "1"))
    lease_seconds = int(os.environ.get("ORACLE_ARC_WORKER_LEASE_SECONDS", "120"))
    worker = PlatformWorker(database_path, token)
    stop = threading.Event()

    def request_stop(_signum, _frame):
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    worker.run_forever(stop, poll_interval=poll_interval, lease_seconds=lease_seconds)


if __name__ == "__main__":
    main()
