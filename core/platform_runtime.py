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
                manifest: dict[str, Any], tool_authorizer: Callable[[str], bool] | None = None) -> dict[str, Any]:
        handler = self._handlers.get(runtime_id)
        if handler is None:
            raise RuntimeUnavailable("No platform-installed handler exists for this runtime")
        if manifest.get("runtime") != runtime_id:
            raise PermissionError("Execution runtime does not match the published agent manifest")
        if manifest.get("allowed_tools"):
            if tool_authorizer is None:
                raise PermissionError("Tool-enabled execution requires a live per-call authorizer")
            result = handler(execution, manifest, tool_authorizer)
        else:
            result = handler(execution, manifest)
        if not isinstance(result, dict):
            raise RuntimeError("Trusted runtime returned an invalid result")
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 1_000_000:
            raise ValueError("Runtime output exceeds one megabyte")
        return result


def _ollama_agent_runtime(execution: dict[str, Any], manifest: dict[str, Any],
                          tool_authorizer: Callable[[str], bool] | None = None) -> dict[str, Any]:
    """Local text runtime with platform-installed tools and per-call authorization."""
    if execution.get("model_provider") != "ollama":
        raise RuntimeUnavailable("This installed runtime currently supports Ollama routes only")
    allowed_tools = manifest.get("allowed_tools", [])
    if not isinstance(allowed_tools, list):
        raise ValueError("Agent tool grants must be a list")
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
    from core.platform_tools import default_tool_registry
    gateway = ModelGateway(provider_id="ollama")
    registry = default_tool_registry()
    tool_definitions = registry.definitions(allowed_tools, execution.get("classification", "private"))
    if allowed_tools and tool_authorizer is None:
        raise PermissionError("Tool-enabled execution requires live per-call authorization")
    total_input_tokens = 0
    total_output_tokens = 0
    answer = None
    # Bounded tool loop: no more than five model turns and eight tool invocations.
    for turn in range(5):
        response = gateway.chat(
            model=execution["model_id"], messages=messages,
            tools=tool_definitions or None, stream=False, temperature=float(temperature))
        message = getattr(response, "message", None)
        if message is None and isinstance(response, dict):
            message = response.get("message") or {}
        for source in ("prompt_eval_count", "eval_count"):
            value = getattr(response, source, None)
            if value is None and isinstance(response, dict):
                value = response.get(source)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                if source == "prompt_eval_count":
                    total_input_tokens += value
                else:
                    total_output_tokens += value
        calls = getattr(message, "tool_calls", None)
        if calls is None and isinstance(message, dict):
            calls = message.get("tool_calls")
        if not calls:
            answer = getattr(message, "content", None)
            if answer is None and isinstance(message, dict):
                answer = message.get("content")
            break
        if turn == 4:
            raise RuntimeError("Model exceeded the maximum tool-use turns")
        assistant_message = {"role": "assistant", "content": getattr(message, "content", "") or "",
                             "tool_calls": []}
        tool_messages = []
        for call in calls:
            function = getattr(call, "function", None)
            if function is None and isinstance(call, dict):
                function = call.get("function", {})
            name = getattr(function, "name", None)
            arguments = getattr(function, "arguments", None)
            if isinstance(function, dict):
                name = function.get("name")
                arguments = function.get("arguments")
            if not isinstance(name, str) or not isinstance(arguments, dict):
                raise ValueError("Model returned a malformed tool call")
            if not tool_authorizer(name):
                raise PermissionError("Tool invocation was denied by live execution policy")
            tool_result = registry.execute(
                name, arguments, allowed_tools=allowed_tools,
                classification=execution.get("classification", "private"))
            assistant_message["tool_calls"].append({
                "type": "function", "function": {"name": name, "arguments": arguments}})
            tool_messages.append({"role": "tool", "content": json.dumps(tool_result, separators=(",", ":"))})
        messages.append(assistant_message)
        messages.extend(tool_messages)
        if len(messages) > 110:
            raise ValueError("Tool execution exceeded the conversation message limit")
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("Model provider returned no text content")
    result: dict[str, Any] = {"answer": answer}
    if total_input_tokens:
        result["input_tokens"] = total_input_tokens
    if total_output_tokens:
        result["output_tokens"] = total_output_tokens
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
