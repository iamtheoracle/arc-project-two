"""Agent registry: versioning, lifecycle, health, and per-agent risk ceilings."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from .types import ArcError, PermissionDenied, Risk


def _vtuple(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


@dataclass
class AgentSpec:
    name: str
    version: str
    role: str
    system_prompt: str
    max_risk: Risk = Risk.READ
    memory_namespaces: tuple = ()                 # which memory spaces this agent may read/write
    health_check: Optional[Callable[[], bool]] = None
    state: str = "active"                         # active | suspended | retired


class AgentRegistry:
    def __init__(self, audit=None):
        self._agents: dict = {}
        self._history: dict = {}
        self._lock = threading.Lock()
        self._audit = audit

    def register(self, spec: AgentSpec) -> None:
        with self._lock:
            cur = self._agents.get(spec.name)
            if cur and _vtuple(spec.version) <= _vtuple(cur.version):
                raise ValueError(f"{spec.name}: version {spec.version} must be newer than {cur.version}")
            if cur:
                self._history.setdefault(spec.name, []).append(cur.version)
            self._agents[spec.name] = spec
        if self._audit:
            self._audit.append("agent.registered", agent=spec.name, version=spec.version)

    def get_active(self, name: str) -> AgentSpec:
        spec = self._agents.get(name)
        if not spec:
            raise PermissionDenied(f"unknown agent: {name}")
        if spec.state != "active":
            raise PermissionDenied(f"agent {name} is {spec.state}")
        return spec

    def set_state(self, name: str, state: str) -> None:
        if state not in ("active", "suspended", "retired"):
            raise ValueError(state)
        self._agents[name].state = state
        if self._audit:
            self._audit.append("agent.state", agent=name, state=state)

    def health(self) -> dict:
        out = {}
        for name, spec in self._agents.items():
            ok = True
            if spec.health_check:
                try:
                    ok = bool(spec.health_check())
                except Exception:
                    ok = False
            out[name] = {"version": spec.version, "state": spec.state, "healthy": ok}
        return out

    def names(self) -> list:
        return sorted(self._agents)
