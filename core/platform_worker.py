"""Trusted Oracle Arc platform worker runtime and daemon loop.

The runner claims only its own application's work, revalidates policy before inference,
renews leases while a model call is active, and atomically commits output plus provider
usage. Tools remain denied until a scoped tool broker is implemented.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from core.model_gateway import ModelGateway
from core.platform_control_plane import PlatformControlPlane
from core.worker_identity import WorkerIdentityStore


class PlatformWorker:
    def __init__(self, database_path: str, worker_token: str):
        self.database_path = database_path
        self.identities = WorkerIdentityStore(database_path)
        self.identity = self.identities.authenticate(worker_token)
        self.control = PlatformControlPlane(database_path)
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
        if row["model_provider"] != "ollama" and row["classification"] != "public":
            raise PermissionError("Remote model providers may process public data only")
        if manifest["allowed_tools"]:
            raise PermissionError("No scoped tool broker is enabled; tool execution is denied")
        return dict(row), {
            "manifest": manifest,
            "route": {"provider_id": row["model_provider"], "model_id": row["model_id"]},
        }

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
            + " Follow the user's request, state uncertainty, and never claim tools or actions "
            "were used unless a trusted tool result is supplied. No tools are available in this run."
        )
        return [{"role": "system", "content": system}] + safe

    @staticmethod
    def _field(response: Any, key: str, default: Any = None) -> Any:
        if isinstance(response, dict):
            return response.get(key, default)
        return getattr(response, key, default)

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
        execution_timeout = float(__import__("os").environ.get(
            "ORACLE_ARC_EXECUTION_TIMEOUT_SECONDS", "300"
        ))
        if not 1 <= execution_timeout <= 3600:
            raise ValueError("ORACLE_ARC_EXECUTION_TIMEOUT_SECONDS must be between 1 and 3600")
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
        deadline = time.monotonic() + execution_timeout
        try:
            self.identities.validate(self.identity, "execution.complete")
            row, context = self._execution_context(execution.execution_id, self.identity.worker_id)
            payload = json.loads(row["input_json"])
            messages = self._messages(payload, context["manifest"])
            reasoning_context, reasoning_trace = self._reasoning_policy(messages)
            messages[0]["content"] += "\n\n" + reasoning_context
            memory_context, memory_trace = self._spark_memory_context(row, payload)
            if memory_context:
                messages[0]["content"] += "\n\n" + memory_context
            self.identities.validate(self.identity, "execution.complete")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("execution_deadline_exceeded")
            provider_id = context["route"]["provider_id"]
            configured_provider_timeout = float(
                __import__("os").environ.get(
                    "ORACLE_ARC_OLLAMA_TIMEOUT_SECONDS" if provider_id == "ollama"
                    else "ORACLE_ARC_REMOTE_PROVIDER_TIMEOUT_SECONDS",
                    "120" if provider_id == "ollama" else "30",
                )
            )
            if not 0 < configured_provider_timeout <= 900:
                raise ValueError("Configured provider timeout must be greater than 0 and at most 900 seconds")
            gateway = ModelGateway(
                provider_id=provider_id,
                timeout_seconds=min(remaining, configured_provider_timeout),
            )
            provider_manifest = gateway.provider_manifest()
            if provider_manifest.get("execution_location") == "remote" and row["classification"] != "public":
                raise PermissionError("Remote model providers may process public data only")
            output_text, usage = self._model_with_tools(
                gateway, context["route"]["model_id"], messages,
                execution.execution_id, self.identity.worker_id,
                context["route"]["provider_id"], deadline, configured_provider_timeout,
            )
            result = {
                "content": output_text,
                "agent_id": execution.agent_id,
                "agent_version": execution.agent_version,
                "provider_id": context["route"]["provider_id"],
                "model_id": context["route"]["model_id"],
                "reasoning_trace": reasoning_trace,
                "spark_memory_trace": memory_trace,
            }
            if time.monotonic() >= deadline:
                raise TimeoutError("execution_deadline_exceeded")
            self.identities.validate(self.identity, "execution.complete")
            self._execution_context(execution.execution_id, self.identity.worker_id)
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
            if isinstance(exc, PermissionError):
                code = "permission_denied"
            elif isinstance(exc, ValueError):
                code = "invalid_execution_request"
            elif isinstance(exc, TimeoutError):
                code = "execution_timeout"
            else:
                code = "worker_execution_failed"
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
            except Exception as exc:
                logger.error(
                    "platform_worker_iteration_failed error_type=%s worker_id=%s",
                    type(exc).__name__, self.identity.worker_id,
                )
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
