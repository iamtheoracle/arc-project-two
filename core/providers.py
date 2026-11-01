"""Provider-independent chat adapters for configured remote model services.

Only fixed provider endpoints are supported. Credentials are read server-side and are
never included in connector metadata or API responses.
"""
from __future__ import annotations

import os
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
        self.timeout_seconds = timeout_seconds
        self.client = client or httpx.Client(timeout=timeout_seconds)

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())

    def chat(self, payload: dict[str, Any]) -> str:
        if not self.configured:
            raise ProviderError("Provider credentials are not configured")
        headers = {self.config.api_key_header: ("Bearer " if self.config.bearer else "") + self.api_key,
                   "Content-Type": "application/json"}
        requested_model = payload.get("model", self.model)
        if (not isinstance(requested_model, str) or not requested_model.strip()
                or len(requested_model) > 256 or any(ord(ch) < 32 for ch in requested_model)):
            raise ValueError("Invalid provider model identifier")
        temperature = payload.get("temperature", 0.4)
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
            raise ValueError("Temperature must be between 0 and 2")
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("Provider request requires messages")
        body = {"model": requested_model, "messages": messages, "temperature": float(temperature)}
        try:
            response = self.client.post(self.config.endpoint, headers=headers,
                                        json=body, timeout=self.timeout_seconds)
            response.raise_for_status()
            data = response.json()
            answer = data["choices"][0]["message"]["content"]
            if not isinstance(answer, str) or not answer.strip():
                raise ProviderError("Provider returned an empty response")
            usage = data.get("usage") if isinstance(data, dict) else None
            result = {"answer": answer}
            if isinstance(usage, dict):
                for source, target in (("prompt_tokens", "input_tokens"),
                                       ("completion_tokens", "output_tokens")):
                    value = usage.get(source)
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        result[target] = value
            return result
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Configured model provider request failed") from exc
