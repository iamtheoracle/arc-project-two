"""Optional remote provider through an OpenAI-compatible API (OpenRouter, Groq, Gemini-compat, ...).

Never used unless the routing policy allows remote inference AND the request's data class is permitted
to leave the machine. The API key is read from the environment and is never logged.
"""
import os
import time

from ..types import ChatRequest, ChatResult, estimate_tokens
from .http import post_json


class OpenAICompatBackend:
    local = False

    def __init__(self, name: str, base_url: str, model: str, api_key_env: str, cost_per_1k: float = 0.0,
                 timeout: float = 60.0):
        self.name, self.base_url, self.model = name, base_url.rstrip("/"), model
        self.api_key_env, self.cost_per_1k, self.timeout = api_key_env, cost_per_1k, timeout

    def health(self) -> bool:
        return bool(os.environ.get(self.api_key_env))

    def chat(self, req: ChatRequest) -> ChatResult:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise RuntimeError(f"{self.api_key_env} is not set")
        t0 = time.perf_counter()
        body = {"model": self.model, "messages": req.messages, "temperature": req.temperature,
                "max_tokens": req.max_tokens}
        if req.json_mode:
            body["response_format"] = {"type": "json_object"}
        data = post_json(self.base_url + "/chat/completions", body,
                         headers={"Authorization": f"Bearer {key}"}, timeout=self.timeout)
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
        pt = usage.get("prompt_tokens") or estimate_tokens(str(req.messages))
        ct = usage.get("completion_tokens") or estimate_tokens(text)
        return ChatResult(text=text, model=self.model, backend=self.name, prompt_tokens=pt, completion_tokens=ct,
                          latency_ms=(time.perf_counter() - t0) * 1000,
                          cost=(pt + ct) / 1000.0 * self.cost_per_1k)
