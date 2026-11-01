"""Trusted runtime dispatch for Oracle Arc.

Only platform-installed handlers are registered here. Agent manifests select a
runtime identifier; they never provide executable source or import paths.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlsplit
from typing import Any, Callable


class RuntimeUnavailable(RuntimeError):
    pass


class TrustedRuntimeRegistry:
    def __init__(self):
        self._handlers: dict[str, Callable] = {}

    @property
    def runtime_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def register(self, runtime_id: str, handler: Callable) -> None:
        if not isinstance(runtime_id, str) or not runtime_id.strip() or len(runtime_id) > 128:
            raise ValueError("Invalid trusted runtime identifier")
        if not callable(handler) or runtime_id in self._handlers:
            raise ValueError("Invalid or duplicate trusted runtime handler")
        self._handlers[runtime_id] = handler

    def execute(self, runtime_id: str, execution: dict[str, Any],
                manifest: dict[str, Any]) -> dict[str, Any]:
        handler = self._handlers.get(runtime_id)
        if handler is None:
            raise RuntimeUnavailable("No platform-installed handler exists for this runtime")
        if manifest.get("runtime") != runtime_id:
            raise PermissionError("Execution runtime does not match the published agent manifest")
        result = handler(execution, manifest)
        if not isinstance(result, dict):
            raise RuntimeError("Trusted runtime returned an invalid result")
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 1_000_000:
            raise ValueError("Runtime output exceeds one megabyte")
        return result


def _ollama_agent_runtime(execution: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Minimal text runtime. Tools remain unavailable until trusted tool adapters exist."""
    if execution.get("model_provider") != "ollama":
        raise RuntimeUnavailable("This installed runtime currently supports Ollama routes only")
    if manifest.get("allowed_tools"):
        raise RuntimeUnavailable("This runtime has no approved tool adapters installed")
    try:
        payload = json.loads(execution["input_json"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Execution payload is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) - {"messages", "temperature"}:
        raise ValueError("Runtime payload must contain only messages and optional temperature")
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError("Runtime payload requires a messages array")
    temperature = payload.get("temperature", 0.4)
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
        raise ValueError("Temperature must be a number between 0 and 2")

    # The first runtime is deliberately local-only. Environment flags must not
    # silently turn a local route into an unreviewed remote data-egress path.
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip()
    parsed = urlsplit(host)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeUnavailable("This runtime permits local Ollama only; remote egress is not enabled")
    # Import at execution time so control-plane API processes do not initialize
    # a model client until an actual workload is run.
    from core.model_gateway import ModelGateway
    response = ModelGateway(provider_id="ollama").chat(
        model=execution["model_id"], messages=messages,
        tools=None, stream=False, temperature=float(temperature))
    message = getattr(response, "message", None)
    answer = getattr(message, "content", None)
    if answer is None and isinstance(response, dict):
        answer = (response.get("message") or {}).get("content")
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("Model provider returned no text content")
    result: dict[str, Any] = {"answer": answer}
    for source, target in (("prompt_eval_count", "input_tokens"),
                           ("eval_count", "output_tokens")):
        value = getattr(response, source, None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[target] = value
    return result


def _remote_agent_runtime(execution: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Opt-in remote text runtime with explicit application route and data policy."""
    if os.environ.get("ORACLE_ARC_ENABLE_REMOTE_INFERENCE", "false").lower() != "true":
        raise RuntimeUnavailable("Remote inference is disabled by the platform operator")
    if manifest.get("allowed_tools"):
        raise RuntimeUnavailable("Remote runtime has no approved tool adapters installed")
    provider = execution.get("model_provider")
    if provider not in {"openrouter", "groq", "gemini"}:
        raise RuntimeUnavailable("Remote runtime requires an approved remote provider route")
    if execution.get("region") != "unspecified":
        raise RuntimeUnavailable("Remote provider residency is not attested; route must use unspecified region")
    classification = execution.get("classification")
    if classification not in {"public", "internal", "private"}:
        raise PermissionError("This remote runtime does not accept sensitive or restricted data")
    try:
        payload = json.loads(execution["input_json"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Execution payload is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) - {"messages", "temperature"}:
        raise ValueError("Runtime payload must contain only messages and optional temperature")
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError("Runtime payload requires a messages array")
    temperature = payload.get("temperature", 0.4)
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
        raise ValueError("Temperature must be a number between 0 and 2")
    from core.privacy_gateway import InferencePolicy, PrivacyAwareModelGateway
    policy = InferencePolicy(
        tenant_id=execution["tenant_id"],
        application_id=execution["application_id"],
        allowed_providers=(provider,),
        data_classification=classification,
        allow_remote=True,
        allowed_regions=("unspecified",),
    )
    response = PrivacyAwareModelGateway().chat(
        policy, model=execution["model_id"], messages=messages,
        temperature=float(temperature), provider_id=provider,
    )
    answer = response.get("answer") if isinstance(response, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("Remote model provider returned no text content")
    return response


def default_runtime_registry() -> TrustedRuntimeRegistry:
    registry = TrustedRuntimeRegistry()
    registry.register("oracle-arc-agent-v1", _ollama_agent_runtime)
    registry.register("oracle-arc-remote-agent-v1", _remote_agent_runtime)
    return registry


def trusted_runtime_ids() -> set[str]:
    """Intersection of operator configuration and code-installed handlers."""
    configured = {x.strip() for x in os.environ.get(
        "ORACLE_ARC_TRUSTED_RUNTIME_IDS", "oracle-arc-agent-v1,oracle-arc-remote-agent-v1").split(",") if x.strip()}
    return configured.intersection(default_runtime_registry().runtime_ids)
