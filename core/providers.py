"""Provider-independent chat adapters for configured remote model services.

Only fixed provider endpoints are supported. Credentials are read server-side and are
never included in connector metadata or API responses.
"""
from __future__ import annotations

import os
import math
import json
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class ProviderConfig:
    provider_id: str
    endpoint: str
    api_key_env: str
    model_env: str
    default_model: str
    api_key_header: str = "Authorization"
    bearer: bool = True


PROVIDERS = (
    ProviderConfig("openrouter", "https://openrouter.ai/api/v1/chat/completions", "ORACLE_ARC_OPENROUTER_API_KEY", "ORACLE_ARC_OPENROUTER_MODEL", "openai/gpt-4o-mini"),
    ProviderConfig("groq", "https://api.groq.com/openai/v1/chat/completions", "ORACLE_ARC_GROQ_API_KEY", "ORACLE_ARC_GROQ_MODEL", "llama-3.3-70b-versatile"),
    ProviderConfig("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "ORACLE_ARC_GEMINI_API_KEY", "ORACLE_ARC_GEMINI_MODEL", "gemini-2.5-flash", "x-goog-api-key", False),
)


class ProviderError(RuntimeError):
    pass


class OpenAICompatibleProvider:
    def __init__(self, config: ProviderConfig, api_key: str | None = None,
                 model: str | None = None, timeout_seconds: float = 30.0,
                 client: httpx.Client | None = None):
        self.config = config
        self.api_key = api_key if api_key is not None else os.environ.get(config.api_key_env, "")
        self.model = model or os.environ.get(config.model_env, config.default_model)
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 900):
            raise ValueError("Remote provider timeout must be greater than 0 and at most 900 seconds.")
        self.timeout_seconds = float(timeout_seconds)
        self.client = client or httpx.Client(timeout=self.timeout_seconds)

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())

    def chat_response(self, payload: dict[str, Any], *,
                      tools: list[dict[str, Any]] | None = None,
                      temperature: float = 0.4,
                      model: str | None = None) -> dict[str, Any]:
        if not self.configured:
            raise ProviderError("Provider credentials are not configured")
        headers = {self.config.api_key_header: ("Bearer " if self.config.bearer else "") + self.api_key,
                   "Content-Type": "application/json"}
        body = {
            "model": model or self.model,
            "messages": payload["messages"],
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        try:
            response = self.client.post(self.config.endpoint, headers=headers,
                                        json=body, timeout=self.timeout_seconds)
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
            if not isinstance(message, dict):
                raise ProviderError("Provider returned an invalid message")
            content = message.get("content")
            tool_calls = message.get("tool_calls") or []
            if (not isinstance(content, str) or not content.strip()) and not tool_calls:
                raise ProviderError("Provider returned an empty response")
            usage = data.get("usage") or {}
            if not isinstance(usage, dict):
                usage = {}
            return {
                "message": message,
                "prompt_eval_count": int(usage.get("prompt_tokens", 0) or 0),
                "eval_count": int(usage.get("completion_tokens", 0) or 0),
            }
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Configured model provider request failed") from exc

    def chat(self, payload: dict[str, Any]) -> str:
        response = self.chat_response(payload)
        content = response["message"].get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("Provider returned a tool call without a text response")
        return content


class AnthropicMessagesProvider:
    """Native Claude Messages API adapter normalized to Oracle Arc's tool contract."""

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 timeout_seconds: float = 30.0, client: httpx.Client | None = None):
        self.api_key = api_key if api_key is not None else os.environ.get("ORACLE_ARC_CLAUDE_API_KEY", "")
        self.model = model or os.environ.get("ORACLE_ARC_CLAUDE_MODEL", "claude-sonnet-4-5")
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 900):
            raise ValueError("Claude provider timeout must be greater than 0 and at most 900 seconds.")
        self.timeout_seconds = float(timeout_seconds)
        self.client = client or httpx.Client(timeout=self.timeout_seconds)
        self.endpoint = "https://api.anthropic.com/v1/messages"

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())

    @staticmethod
    def _convert_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []
        for item in messages:
            role = item.get("role")
            content = item.get("content", "")
            if role == "system":
                if isinstance(content, str) and content.strip():
                    system_parts.append(content)
                continue
            if role == "tool":
                call_id = item.get("tool_call_id")
                if not isinstance(call_id, str) or not call_id:
                    raise ProviderError("Claude tool result is missing its call identifier")
                converted.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "content": content,
                    }],
                })
                continue
            if role not in {"user", "assistant"}:
                raise ProviderError("Claude received an unsupported message role")
            blocks: list[dict[str, Any]] = []
            if isinstance(content, str) and content.strip():
                blocks.append({"type": "text", "text": content})
            calls = item.get("tool_calls") or []
            if calls and role != "assistant":
                raise ProviderError("Only assistant messages may contain tool calls")
            for call in calls:
                call_id = call.get("id")
                function = call.get("function") or {}
                name = function.get("name")
                arguments = function.get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError as exc:
                        raise ProviderError("Claude tool arguments are invalid JSON") from exc
                if (not isinstance(call_id, str) or not call_id
                        or not isinstance(name, str) or not name
                        or not isinstance(arguments, dict)):
                    raise ProviderError("Claude tool call is malformed")
                blocks.append({
                    "type": "tool_use",
                    "id": call_id,
                    "name": name,
                    "input": arguments,
                })
            if not blocks:
                blocks.append({"type": "text", "text": " "})
            converted.append({
                "role": role,
                "content": blocks if any(block["type"] != "text" for block in blocks) else blocks[0]["text"],
            })
        if not any(item["role"] == "user" for item in converted):
            raise ProviderError("Claude requests require at least one user message")
        return "\n\n".join(system_parts), converted

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        converted = []
        for item in tools:
            if item.get("type") != "function" or not isinstance(item.get("function"), dict):
                raise ProviderError("Claude tool schema is unsupported")
            function = item["function"]
            name = function.get("name")
            schema = function.get("parameters")
            if not isinstance(name, str) or not name or not isinstance(schema, dict):
                raise ProviderError("Claude tool schema is malformed")
            converted.append({
                "name": name,
                "description": function.get("description", ""),
                "input_schema": schema,
            })
        return converted

    def chat_response(self, payload: dict[str, Any], *,
                      tools: list[dict[str, Any]] | None = None,
                      temperature: float = 0.4,
                      model: str | None = None) -> dict[str, Any]:
        if not self.configured:
            raise ProviderError("Claude provider credentials are not configured")
        if not isinstance(temperature, (int, float)) or isinstance(temperature, bool) or not 0 <= temperature <= 1:
            raise ValueError("Claude temperature must be between 0 and 1")
        system, messages = self._convert_messages(payload["messages"])
        body: dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": int(os.environ.get("ORACLE_ARC_CLAUDE_MAX_TOKENS", "4096")),
            "messages": messages,
            "temperature": temperature,
        }
        if system:
            body["system"] = system
        converted_tools = self._convert_tools(tools)
        if converted_tools:
            body["tools"] = converted_tools
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            response = self.client.post(
                self.endpoint, headers=headers, json=body, timeout=self.timeout_seconds
            )
            response.raise_for_status()
            data = response.json()
            blocks = data.get("content")
            if not isinstance(blocks, list):
                raise ProviderError("Claude returned an invalid response")
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    text_parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    name, call_id, arguments = block.get("name"), block.get("id"), block.get("input")
                    if (not isinstance(name, str) or not isinstance(call_id, str)
                            or not isinstance(arguments, dict)):
                        raise ProviderError("Claude returned a malformed tool call")
                    tool_calls.append({
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments, separators=(",", ":"))},
                    })
            text = "\n".join(text_parts)
            if not text.strip() and not tool_calls:
                raise ProviderError("Claude returned an empty response")
            usage = data.get("usage") or {}
            if not isinstance(usage, dict):
                usage = {}
            return {
                "message": {
                    "role": "assistant",
                    "content": text if text.strip() else " ",
                    "tool_calls": tool_calls,
                },
                "prompt_eval_count": int(usage.get("input_tokens", 0) or 0),
                "eval_count": int(usage.get("output_tokens", 0) or 0),
            }
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ProviderError("Configured Claude provider request failed") from exc

    def set_timeout_seconds(self, timeout_seconds: float) -> None:
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 900):
            raise ValueError("Claude provider timeout must be greater than 0 and at most 900 seconds.")
        self.timeout_seconds = float(timeout_seconds)
