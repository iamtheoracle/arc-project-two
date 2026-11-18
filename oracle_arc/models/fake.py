"""Deterministic scripted backend for tests and offline development. Not a model."""
import time

from ..types import ChatRequest, ChatResult, estimate_tokens


class ScriptedBackend:
    def __init__(self, name="scripted", replies=None, local=True, fail=False, delay=0.0, cost_per_1k=0.0):
        self.name, self.local, self.fail, self.delay, self.cost_per_1k = name, local, fail, delay, cost_per_1k
        self.model = name
        # replies: list (consumed in call order) or {"plan": [...], "chat": [...]} keyed by request purpose.
        self.by_purpose = {k: list(v) for k, v in replies.items()} if isinstance(replies, dict) else None
        self.replies = [] if self.by_purpose is not None else list(replies or [])
        self.calls: list = []

    def health(self) -> bool:
        return not self.fail

    def chat(self, req: ChatRequest) -> ChatResult:
        self.calls.append(req)
        if self.fail:
            raise RuntimeError(f"{self.name} down")
        if self.delay:
            time.sleep(self.delay)
        if self.by_purpose is not None:
            queue = self.by_purpose.get(req.purpose, [])
            default = '{"action":"respond"}' if req.purpose == "plan" else "ok"
            text = queue.pop(0) if queue else default
        else:
            text = self.replies.pop(0) if self.replies else "ok"
        if callable(text):
            text = text(req)
        pt, ct = estimate_tokens(str(req.messages)), estimate_tokens(text)
        return ChatResult(text=text, model=self.model, backend=self.name, prompt_tokens=pt,
                          completion_tokens=ct, latency_ms=self.delay * 1000,
                          cost=(pt + ct) / 1000.0 * self.cost_per_1k)
