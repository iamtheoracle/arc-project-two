"""Explicit user confirmation for consequential actions.

A challenge is bound to the exact action (tool + arguments + amount) by a hash the client must echo
back, is single-use, expires, and can only be completed by the same application and user that
received it. Financial/destructive actions additionally require a step-up authenticator; with none
configured they fail closed.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .types import ConfirmationError, Principal, Risk


def action_hash(tool: str, args: dict) -> str:
    return hashlib.sha256(json.dumps([tool, args], sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass
class Challenge:
    id: str
    app_id: str
    user_id: str
    agent: str
    tool: str
    args: dict
    summary: str
    risk: Risk
    action_hash: str
    expires: float
    used: bool = False


class ConfirmationBroker:
    def __init__(self, ttl_s: float = 300.0, step_up: Optional[Callable[[Principal, dict], bool]] = None,
                 clock=time.time):
        self.ttl_s, self.step_up, self._clock = ttl_s, step_up, clock
        self._ch: dict = {}
        self._lock = threading.Lock()

    def create(self, p: Principal, agent: str, tool: str, args: dict, summary: str, risk: Risk) -> Challenge:
        ch = Challenge(secrets.token_urlsafe(16), p.app_id, p.user_id, agent, tool, dict(args), summary, risk,
                       action_hash(tool, args), self._clock() + self.ttl_s)
        with self._lock:
            self._ch[ch.id] = ch
        return ch

    def consume(self, p: Principal, challenge_id: str, echoed_hash: str, proof: dict = None) -> Challenge:
        with self._lock:
            ch = self._ch.get(challenge_id)
            if not ch:
                raise ConfirmationError("unknown confirmation")
            if ch.app_id != p.app_id or ch.user_id != p.user_id:
                raise ConfirmationError("confirmation belongs to a different user or application")
            if ch.used:
                raise ConfirmationError("confirmation already used")
            if ch.expires < self._clock():
                raise ConfirmationError("confirmation expired")
            if echoed_hash != ch.action_hash:
                raise ConfirmationError("confirmation does not match the action presented")
            if ch.risk >= Risk.FINANCIAL:
                if not self.step_up:
                    raise ConfirmationError("no step-up authenticator configured for high-risk actions")
                if not self.step_up(p, proof or {}):
                    raise ConfirmationError("step-up authentication failed")
            ch.used = True
            return ch
