"""Model gateway: provider-independent routing, fallback, circuit breaking, quotas, caching.

Selection order for a request: eligible backends (privacy policy) -> healthy (circuit closed) ->
configured priority -> measured latency (EWMA). Remote backends are skipped unless policy allows them
and the request's data class is at or below the configured ceiling.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from ..types import ChatRequest, ChatResult, DataClass, ModelUnavailable, QuotaExceeded


@dataclass
class RoutingPolicy:
    allow_remote: bool = False                      # remote inference is opt-in
    remote_max_data_class: DataClass = DataClass.PUBLIC
    failure_threshold: int = 3                      # consecutive failures that open the circuit
    cooldown_s: float = 30.0
    cache_size: int = 256
    cache_ttl_s: float = 300.0


class UsageMeter:
    """Per-application token and cost budgets over a rolling window."""

    def __init__(self, window_s: float = 86400.0, clock=time.time):
        self.window_s, self._clock = window_s, clock
        self._limits: dict = {}
        self._events: dict = {}
        self._lock = threading.Lock()

    def set_limit(self, app_id: str, max_tokens: int = None, max_cost: float = None) -> None:
        self._limits[app_id] = (max_tokens, max_cost)

    def _prune(self, app_id: str):
        cutoff = self._clock() - self.window_s
        self._events[app_id] = [e for e in self._events.get(app_id, []) if e[0] >= cutoff]

    def usage(self, app_id: str) -> dict:
        with self._lock:
            self._prune(app_id)
            ev = self._events.get(app_id, [])
            return {"tokens": sum(e[1] for e in ev), "cost": sum(e[2] for e in ev), "calls": len(ev)}

    def check(self, app_id: str) -> None:
        mt, mc = self._limits.get(app_id, (None, None))
        u = self.usage(app_id)
        if mt is not None and u["tokens"] >= mt:
            raise QuotaExceeded("token quota exhausted", app_id=app_id)
        if mc is not None and u["cost"] >= mc:
            raise QuotaExceeded("cost quota exhausted", app_id=app_id)

    def record(self, app_id: str, tokens: int, cost: float) -> None:
        with self._lock:
            self._events.setdefault(app_id, []).append((self._clock(), tokens, cost))


class _Health:
    def __init__(self):
        self.failures = 0
        self.open_until = 0.0
        self.ewma_ms = None


class ModelGateway:
    def __init__(self, backends: list, policy: RoutingPolicy = None, meter: UsageMeter = None, clock=time.time):
        self.backends = list(backends)           # order == priority
        self.policy = policy or RoutingPolicy()
        self.meter = meter or UsageMeter()
        self._clock = clock
        self._health = {b.name: _Health() for b in self.backends}
        self._cache: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    # ---- eligibility -------------------------------------------------------------------------
    def _eligible(self, req: ChatRequest) -> list:
        out = []
        for i, b in enumerate(self.backends):
            if not getattr(b, "local", True):
                if not self.policy.allow_remote or req.data_class > self.policy.remote_max_data_class:
                    continue
            out.append((i, b))
        now = self._clock()

        # Closed circuits first; among them keep configured priority, using measured latency to break
        # ties between backends of the same locality class.
        ranked = sorted(out, key=lambda it: (self._health[it[1].name].open_until > now,
                                              0 if getattr(it[1], "local", True) else 1,
                                              self._health[it[1].name].ewma_ms
                                              if self._health[it[1].name].ewma_ms is not None else 0.0,
                                              it[0]))
        return [b for _, b in ranked]

    # ---- cache -------------------------------------------------------------------------------
    def _ckey(self, req: ChatRequest) -> str:
        raw = json.dumps([req.messages, req.max_tokens, req.json_mode, int(req.data_class)], sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _cache_get(self, req: ChatRequest):
        if req.temperature != 0 or self.policy.cache_size <= 0:
            return None
        with self._lock:
            hit = self._cache.get(self._ckey(req))
            if hit and hit[0] > self._clock():
                self._cache.move_to_end(self._ckey(req))
                return hit[1]
        return None

    def _cache_put(self, req: ChatRequest, res: ChatResult) -> None:
        if req.temperature != 0 or self.policy.cache_size <= 0:
            return
        with self._lock:
            self._cache[self._ckey(req)] = (self._clock() + self.policy.cache_ttl_s, res)
            while len(self._cache) > self.policy.cache_size:
                self._cache.popitem(last=False)

    # ---- main entry --------------------------------------------------------------------------
    def chat(self, req: ChatRequest, app_id: str = "") -> ChatResult:
        if app_id:
            self.meter.check(app_id)
        cached = self._cache_get(req)
        if cached is not None:
            return ChatResult(**{**cached.__dict__, "cached": True, "latency_ms": 0.0, "cost": 0.0})
        reasons: list = []
        for b in self._eligible(req):
            h = self._health[b.name]
            if h.open_until > self._clock():
                reasons.append(f"{b.name}: circuit open")
                continue
            try:
                res = b.chat(req)
            except Exception as e:  # provider failure -> fall back to the next backend
                h.failures += 1
                if h.failures >= self.policy.failure_threshold:
                    h.open_until = self._clock() + self.policy.cooldown_s
                reasons.append(f"{b.name}: {type(e).__name__}: {e}")
                continue
            h.failures = 0
            h.ewma_ms = res.latency_ms if h.ewma_ms is None else 0.7 * h.ewma_ms + 0.3 * res.latency_ms
            if app_id:
                self.meter.record(app_id, res.prompt_tokens + res.completion_tokens, res.cost)
            self._cache_put(req, res)
            return res
        if not reasons:
            reasons.append("no backend is permitted for this request's data class")
        raise ModelUnavailable("no model backend could serve the request", reasons=reasons)

    def status(self) -> list:
        now = self._clock()
        return [{"name": b.name, "local": getattr(b, "local", True), "model": getattr(b, "model", ""),
                 "circuit_open": self._health[b.name].open_until > now,
                 "ewma_ms": self._health[b.name].ewma_ms} for b in self.backends]
