"""Bounded in-process token-bucket rate limiting (A11).

Per-process only: with several gateway processes each has its own buckets, so the effective limit is
N x the configured rate. Distributed limiting needs a shared store and is Planned. Memory is bounded by
`max_keys`; when full, the least recently used bucket is evicted (an attacker rotating keys can reset
their own bucket, which is why a per-application limit is applied as well as a per-user one).
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

from .types import RateLimited


class RateLimiter:
    def __init__(self, rate_per_s: float, burst: float, max_keys: int = 10_000, clock=time.monotonic):
        if rate_per_s <= 0 or burst < 1 or max_keys < 1:
            raise ValueError("rate_per_s must be > 0, burst >= 1 and max_keys >= 1")
        self.rate, self.burst, self.max_keys, self._clock = float(rate_per_s), float(burst), max_keys, clock
        self._b: "OrderedDict[str, tuple]" = OrderedDict()      # key -> (tokens, last)
        self._lock = threading.Lock()

    def check(self, key: str, cost: float = 1.0) -> None:
        """Consume `cost` tokens or raise RateLimited with an accurate retry_after."""
        now = self._clock()
        with self._lock:
            tokens, last = self._b.pop(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens >= cost:
                self._b[key] = (tokens - cost, now)
                allowed, wait = True, 0.0
            else:
                self._b[key] = (tokens, now)
                allowed, wait = False, (cost - tokens) / self.rate
            while len(self._b) > self.max_keys:
                self._b.popitem(last=False)
        if not allowed:
            raise RateLimited(retry_after=max(wait, 0.001))

    def peek(self, key: str, cost: float = 1.0) -> None:
        """Raise RateLimited if `cost` tokens are not available, without consuming any."""
        now = self._clock()
        with self._lock:
            tokens, last = self._b.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            wait = 0.0 if tokens >= cost else (cost - tokens) / self.rate
        if wait:
            raise RateLimited(retry_after=max(wait, 0.001))

    def charge(self, key: str, cost: float = 1.0) -> None:
        """Consume tokens if available; never raises (used to record a failure after the fact)."""
        try:
            self.check(key, cost)
        except RateLimited:
            pass

    def __len__(self) -> int:
        return len(self._b)
