"""Agent, plugin and session connector registries for Oracle Arc.

Registries contain trusted Python handlers supplied by application wiring. They never
discover or import arbitrary plugin files. A deployment must provide distinct connector
endpoints to obtain real provider failover.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


class RegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    name: str
    role: str
    capabilities: tuple[str, ...]
    enabled: bool = True


@dataclass
class Connector:
    connector_id: str
    provider: str
    priority: int
    handler: Callable[[dict[str, Any]], Any]
    enabled: bool = True
    failure_threshold: int = 2
    cooldown_seconds: float = 30.0
    failures: int = 0
    unavailable_until: float = 0.0
    last_error: str | None = None

    def available(self, now: float | None = None) -> bool:
        return self.enabled and (now if now is not None else time.monotonic()) >= self.unavailable_until

    def invoke(self, payload: dict[str, Any]) -> Any:
        try:
            result = self.handler(payload)
            if result is None:
                raise RegistryError("Connector returned no result")
            self.failures = 0
            self.unavailable_until = 0.0
            self.last_error = None
            return result
        except Exception as exc:
            self.failures += 1
            self.last_error = type(exc).__name__
            if self.failures >= self.failure_threshold:
                self.unavailable_until = time.monotonic() + self.cooldown_seconds
            raise


class AgentRegistry:
    """Routes a task to an agent's healthiest available connector, in priority order."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentDefinition] = {}
        self._connectors: dict[str, list[Connector]] = {}

    def register_agent(self, definition: AgentDefinition) -> None:
        if not definition.agent_id or definition.agent_id in self._agents:
            raise RegistryError("Agent ID must be unique and non-empty")
        self._agents[definition.agent_id] = definition
        self._connectors[definition.agent_id] = []

    def register_connector(self, agent_id: str, connector: Connector) -> None:
        if agent_id not in self._agents:
            raise RegistryError("Register the agent before its connectors")
        connectors = self._connectors[agent_id]
        if any(item.connector_id == connector.connector_id for item in connectors):
            raise RegistryError("Connector ID must be unique per agent")
        connectors.append(connector)
        connectors.sort(key=lambda item: item.priority)

    def list_agents(self) -> list[dict[str, Any]]:
        rows = []
        for agent in self._agents.values():
            connectors = self._connectors[agent.agent_id]
            rows.append({
                "agent_id": agent.agent_id,
                "name": agent.name,
                "role": agent.role,
                "capabilities": list(agent.capabilities),
                "enabled": agent.enabled,
                "connectors": [
                    {"connector_id": c.connector_id, "provider": c.provider,
                     "priority": c.priority, "enabled": c.enabled,
                     "healthy": c.available()}
                    for c in connectors
                ],
                "connected": any(c.available() for c in connectors),
            })
        return rows

    def dispatch(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        agent = self._agents.get(agent_id)
        if agent is None or not agent.enabled:
            raise RegistryError("Agent is unknown or disabled")
        connectors = self._connectors[agent_id]
        attempted: list[str] = []
        for connector in connectors:
            if not connector.available():
                continue
            attempted.append(connector.connector_id)
            try:
                result = connector.invoke(payload)
                return {"agent_id": agent_id, "connector_id": connector.connector_id,
                        "provider": connector.provider, "result": result,
                        "fallback_used": len(attempted) > 1}
            except Exception:
                continue
        raise RegistryError("No healthy connector could complete this request")


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    version: str
    description: str
    required_permissions: tuple[str, ...] = ()
    enabled: bool = False


class PluginCatalog:
    """Metadata-only plugin catalogue; execution must be wired to a trusted worker."""

    def __init__(self) -> None:
        self._manifests: dict[str, PluginManifest] = {}

    def register(self, manifest: PluginManifest) -> None:
        if not manifest.plugin_id or manifest.plugin_id in self._manifests:
            raise RegistryError("Plugin ID must be unique and non-empty")
        self._manifests[manifest.plugin_id] = manifest

    def list_plugins(self) -> list[dict[str, Any]]:
        return [
            {"plugin_id": item.plugin_id, "version": item.version,
             "description": item.description,
             "required_permissions": list(item.required_permissions),
             "enabled": item.enabled}
            for item in self._manifests.values()
        ]


class SessionConnector:
    """Ordered session persistence adapters with fallback on connector failure."""

    def __init__(self, connector_id: str, priority: int,
                 load: Callable[[str], Any], save: Callable[[str, Any], Any]) -> None:
        self.connector_id = connector_id
        self.priority = priority
        self.load_handler = load
        self.save_handler = save
        self.failures = 0
        self.unavailable_until = 0.0

    def available(self) -> bool:
        return time.monotonic() >= self.unavailable_until

    def load(self, session_id: str) -> Any:
        return self.load_handler(session_id)

    def save(self, session_id: str, value: Any) -> Any:
        return self.save_handler(session_id, value)


class SessionConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: list[SessionConnector] = []

    def register(self, connector: SessionConnector) -> None:
        if any(c.connector_id == connector.connector_id for c in self._connectors):
            raise RegistryError("Session connector ID must be unique")
        self._connectors.append(connector)
        self._connectors.sort(key=lambda c: c.priority)

    def _run(self, operation: str, *args: Any) -> dict[str, Any]:
        attempted = []
        for connector in self._connectors:
            if not connector.available():
                continue
            attempted.append(connector.connector_id)
            try:
                handler = connector.load if operation == "load" else connector.save
                result = handler(*args)
                connector.failures = 0
                connector.unavailable_until = 0.0
                return {"connector_id": connector.connector_id, "result": result,
                        "fallback_used": len(attempted) > 1}
            except Exception:
                connector.failures += 1
                if connector.failures >= 2:
                    connector.unavailable_until = time.monotonic() + 30.0
        raise RegistryError("No healthy session connector is available")

    def load(self, session_id: str) -> dict[str, Any]:
        return self._run("load", session_id)

    def save(self, session_id: str, value: Any) -> dict[str, Any]:
        return self._run("save", session_id, value)


def default_agent_registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register_agent(AgentDefinition(
        "bud", "BUD", "Everyday companion and agent coordinator",
        ("conversation", "task_routing", "session_continuity")))
    registry.register_agent(AgentDefinition(
        "oracle", "ORACLE", "Reasoning, research and problem-solving",
        ("reasoning", "analysis", "planning")))
    registry.register_agent(AgentDefinition(
        "spark", "SPARK", "Permissioned memory and continuity",
        ("memory", "retrieval", "memory_governance"), enabled=False))
    registry.register_agent(AgentDefinition(
        "orbits", "ORBITS", "Visual understanding and creative workflows",
        ("image_understanding", "visual_analysis", "creative_workflows"), enabled=False))
    return registry
