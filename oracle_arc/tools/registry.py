"""Tools are separately authorised capabilities: a tool existing does not mean an agent may use it."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..types import DataClass, Risk, ValidationError


@dataclass
class ToolSpec:
    name: str
    description: str
    risk: Risk
    parameters: dict                                   # JSON-schema subset: type/required/properties/enum/min/max
    executor: Callable[[dict, Any], Any]               # (args, ToolContext) -> result
    verifier: Optional[Callable[[dict, Any, Any], bool]] = None   # confirms the effect really happened
    describe: Optional[Callable[[dict], str]] = None   # human-readable consequence shown before confirmation
    amount: Optional[Callable[[dict], tuple]] = None   # -> (minor_units:int, currency:str) for financial tools
    match: Optional[Callable[[str], Optional[dict]]] = None       # deterministic fast path; skips the model
    data_class: DataClass = DataClass.INTERNAL


_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}


def validate_args(schema: dict, args: Any) -> dict:
    """Strict validation of tool arguments (model output is untrusted input)."""
    if not isinstance(args, dict):
        raise ValidationError("arguments must be an object")
    props = schema.get("properties", {})
    for req in schema.get("required", []):
        if req not in args:
            raise ValidationError(f"missing required argument: {req}")
    for k, v in args.items():
        if k not in props:
            raise ValidationError(f"unexpected argument: {k}")
        spec = props[k]
        t = _TYPES.get(spec.get("type", ""), object)
        if isinstance(v, bool) and spec.get("type") in ("integer", "number"):
            raise ValidationError(f"{k} must be {spec['type']}")
        if not isinstance(v, t):
            raise ValidationError(f"{k} must be {spec.get('type')}")
        if "enum" in spec and v not in spec["enum"]:
            raise ValidationError(f"{k} must be one of {spec['enum']}")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if "minimum" in spec and v < spec["minimum"]:
                raise ValidationError(f"{k} below minimum")
            if "maximum" in spec and v > spec["maximum"]:
                raise ValidationError(f"{k} above maximum")
        if isinstance(v, str) and len(v) > spec.get("maxLength", 4000):
            raise ValidationError(f"{k} too long")
    return args


class ToolRegistry:
    def __init__(self):
        self._tools: dict = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def names(self) -> list:
        return sorted(self._tools)


class GrantTable:
    """(agent, tool) grants with immediate revocation. Grants are never implied by another agent's."""

    def __init__(self, audit=None):
        self._grants: set = set()
        self._lock = threading.Lock()
        self._audit = audit

    def grant(self, agent: str, tool: str, by: str = "system") -> None:
        with self._lock:
            self._grants.add((agent, tool))
        if self._audit:
            self._audit.append("grant.added", agent=agent, tool=tool, by=by)

    def revoke(self, agent: str, tool: str, by: str = "system") -> None:
        with self._lock:
            self._grants.discard((agent, tool))
        if self._audit:
            self._audit.append("grant.revoked", agent=agent, tool=tool, by=by)

    def allowed(self, agent: str, tool: str) -> bool:
        with self._lock:
            return (agent, tool) in self._grants

    def tools_for(self, agent: str) -> list:
        with self._lock:
            return sorted(t for a, t in self._grants if a == agent)
