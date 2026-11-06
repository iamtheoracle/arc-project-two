"""Local inference through Ollama's HTTP API. Default model direction: Qwen 2.5 7B."""
import os
import time

from ..types import ChatRequest, ChatResult, estimate_tokens
from .http import get_json, post_json


class OllamaBackend:
    local = True

    def __init__(self, model: str = None, host: str = None, name: str = "ollama", timeout: float = 120.0):
        self.name = name
        self.model = model or os.environ.get("ARC_MODEL", "qwen2.5:7b")
        self.host = (host or os.environ.get("ARC_OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = timeout
        self.cost_per_1k = 0.0

    def health(self) -> bool:
        try:
            tags = get_json(self.host + "/api/tags", timeout=2.0)
            names = {m.get("name") for m in tags.get("models", [])}
            return self.model in names or any(n and n.split(":")[0] == self.model.split(":")[0] for n in names)
        except Exception:
            return False

    def chat(self, req: ChatRequest) -> ChatResult:
        t0 = time.perf_counter()
        body = {"model": self.model, "messages": req.messages, "stream": False,
                "options": {"temperature": req.temperature, "num_predict": req.max_tokens}}
        if req.json_mode:
            body["format"] = "json"
        data = post_json(self.host + "/api/chat", body, timeout=self.timeout)
        text = (data.get("message") or {}).get("content", "")
        return ChatResult(text=text, model=self.model, backend=self.name,
                          prompt_tokens=data.get("prompt_eval_count") or estimate_tokens(str(req.messages)),
                          completion_tokens=data.get("eval_count") or estimate_tokens(text),
                          latency_ms=(time.perf_counter() - t0) * 1000)
