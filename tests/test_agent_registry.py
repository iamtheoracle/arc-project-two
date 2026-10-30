import pytest

from core.agent_registry import (
    AgentDefinition, AgentRegistry, Connector, PluginCatalog, PluginManifest,
    RegistryError, SessionConnector, SessionConnectorRegistry, default_agent_registry,
)


def test_default_registry_registers_bud_and_oracle_first():
    registry = default_agent_registry()
    agents = {item["agent_id"]: item for item in registry.list_agents()}
    assert agents["bud"]["enabled"] is True
    assert agents["oracle"]["enabled"] is True
    assert agents["spark"]["enabled"] is False
    assert agents["orbits"]["enabled"] is False


def test_agent_registry_fails_over_to_next_connector():
    registry = AgentRegistry()
    registry.register_agent(AgentDefinition("oracle", "ORACLE", "Reasoning", ("reasoning",)))
    registry.register_connector("oracle", Connector(
        "primary", "ollama-primary", 10,
        lambda payload: (_ for _ in ()).throw(ConnectionError("offline")),
        failure_threshold=1, cooldown_seconds=60,
    ))
    registry.register_connector("oracle", Connector(
        "backup", "ollama-backup", 20,
        lambda payload: {"answer": payload["prompt"]},
    ))
    result = registry.dispatch("oracle", {"prompt": "hello"})
    assert result["connector_id"] == "backup"
    assert result["fallback_used"] is True
    assert result["result"] == {"answer": "hello"}


def test_agent_registry_rejects_unknown_agents_and_duplicate_ids():
    registry = AgentRegistry()
    registry.register_agent(AgentDefinition("bud", "BUD", "Companion", ()))
    with pytest.raises(RegistryError):
        registry.register_agent(AgentDefinition("bud", "Duplicate", "Duplicate", ()))
    with pytest.raises(RegistryError):
        registry.dispatch("missing", {})


def test_plugin_catalog_is_metadata_only_and_disabled_by_default():
    catalog = PluginCatalog()
    catalog.register(PluginManifest("calendar", "1.0.0", "Calendar integration",
                                    ("calendar.read",), enabled=False))
    assert catalog.list_plugins() == [{
        "plugin_id": "calendar", "version": "1.0.0",
        "description": "Calendar integration",
        "required_permissions": ["calendar.read"], "enabled": False,
    }]


def test_session_connector_falls_back_after_primary_failure():
    sessions = {"s1": {"messages": ["hello"]}}
    registry = SessionConnectorRegistry()
    registry.register(SessionConnector(
        "primary", 10,
        lambda session_id: (_ for _ in ()).throw(ConnectionError("db offline")),
        lambda session_id, value: None,
    ))
    registry.register(SessionConnector(
        "backup", 20,
        lambda session_id: sessions[session_id],
        lambda session_id, value: sessions.__setitem__(session_id, value),
    ))
    result = registry.load("s1")
    assert result["connector_id"] == "backup"
    assert result["fallback_used"] is True
    assert result["result"] == {"messages": ["hello"]}
