"""Trusted runtime dispatch for Oracle Arc.

Only platform-installed handlers are registered here. Agent manifests select a
runtime identifier; they never provide executable source or import paths.
"""
from __future__ import annotations

import json
import os
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

    # Import at execution time so non-Ollama platform processes need not initialize
    # a local provider client merely to use the control-plane APIs.
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


def default_runtime_registry() -> TrustedRuntimeRegistry:
    registry = TrustedRuntimeRegistry()
    registry.register("oracle-arc-agent-v1", _ollama_agent_runtime)
    return registry


def trusted_runtime_ids() -> set[str]:
    """Intersection of operator configuration and code-installed handlers."""
    configured = {x.strip() for x in os.environ.get(
        "ORACLE_ARC_TRUSTED_RUNTIME_IDS", "oracle-arc-agent-v1").split(",") if x.strip()}
    return configured.intersection(default_runtime_registry().runtime_ids)
