"""Capability-based implementation planning for Oracle Arc.

This module recommends responsible agents and integration types. It does not install,
enable, import, execute, or grant permissions to plugins or connectors.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CapabilityRule:
    capability: str
    keywords: tuple[str, ...]
    agent_id: str
    plugins: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()
    connectors: tuple[str, ...] = ()
    reason: str = ""


RULES = (
    CapabilityRule(
        "reasoning", ("analyze", "analysis", "research", "compare", "decision", "plan", "debug", "architecture", "implement", "build", "fix", "upgrade", "code", "technical"),
        "oracle", ("calculator",), ("repository-code-assistant", "test-runner"), ("model-gateway", "github"),
        "This work needs technical reasoning, planning or problem-solving.",
    ),
    CapabilityRule(
        "visual", ("image", "visual", "diagram", "design", "screenshot", "illustration", "render"),
        "orbits", (), ("image-understanding", "visual-design"), ("vision-model",),
        "This work depends on visual input or visual output.",
    ),
    CapabilityRule(
        "memory", ("remember", "memory", "recall", "personal context", "preference", "continuity"),
        "spark", (), ("memory-management",), ("memory-store",),
        "This work depends on controlled personal memory or continuity.",
    ),
    CapabilityRule(
        "integration", ("connect", "connector", "plugin", "extension", "api", "github", "database", "provider", "webhook"),
        "oracle", ("integration-catalog",), ("connector-sdk", "extension-manifest-validator"), ("secret-manager", "integration-api"),
        "This work requires a verified external integration and its permissions.",
    ),
    CapabilityRule(
        "conversation", ("explain", "help", "talk", "simple", "understand", "conversation"),
        "bud", (), (), (),
        "This is primarily a conversational or explanation task.",
    ),
)


def plan_implementation(description: str, available_agents: dict[str, bool] | None = None) -> dict[str, Any]:
    """Return a transparent, deterministic recommendation without side effects."""
    if not isinstance(description, str) or not description.strip():
        raise ValueError("A non-empty implementation description is required")
    text = description.casefold()
    matched: list[CapabilityRule] = []
    for rule in RULES:
        if any(keyword in text for keyword in rule.keywords):
            matched.append(rule)
    if not matched:
        matched = [RULES[-1]]

    # A technical/integration request belongs to ORACLE; BUD remains the coordinator.
    primary = "oracle" if any(r.agent_id == "oracle" for r in matched) else matched[0].agent_id
    ordered_agents = [primary]
    for rule in matched:
        if rule.agent_id not in ordered_agents:
            ordered_agents.append(rule.agent_id)

    def unique(values: tuple[str, ...] | list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    capabilities = unique([rule.capability for rule in matched])
    plugins = unique([item for rule in matched for item in rule.plugins])
    extensions = unique([item for rule in matched for item in rule.extensions])
    connectors = unique([item for rule in matched for item in rule.connectors])
    statuses = available_agents or {}
    agent_plan = [
        {
            "agent_id": agent_id,
            "responsibility": {
                "bud": "Coordinate the request and keep the user informed.",
                "oracle": "Own technical analysis, implementation planning and validation.",
                "spark": "Handle only explicitly permitted memory and continuity work.",
                "orbits": "Handle visual analysis and creative output.",
            }[agent_id],
            "registered_and_enabled": statuses.get(agent_id, agent_id in ("bud", "oracle")),
        }
        for agent_id in ordered_agents
    ]
    return {
        "coordinator": "bud",
        "primary_agent": primary,
        "agents": agent_plan,
        "required_capabilities": capabilities,
        "recommended_plugins": [
            {"id": item, "status": "catalogue recommendation only", "auto_install": False}
            for item in plugins
        ],
        "recommended_extensions": [
            {"id": item, "status": "not installed; review manifest and sandbox first", "auto_install": False}
            for item in extensions
        ],
        "recommended_connectors": [
            {"id": item, "status": "must be configured and health-checked", "auto_connect": False}
            for item in connectors
        ],
        "reasons": unique([rule.reason for rule in matched]),
        "execution_authorized": False,
        "approval_required_before_external_side_effects": True,
        "selection_method": "deterministic capability and keyword matching; human review required",
    }
