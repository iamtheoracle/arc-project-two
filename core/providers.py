"""Provider-independent chat adapters for configured remote model services.

Only fixed provider endpoints are supported. Credentials are read server-side and are
never included in connector metadata or API responses.
"""
from __future__ import annotations

import os
import math
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
