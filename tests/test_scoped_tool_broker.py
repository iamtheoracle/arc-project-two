import pytest

from core.scoped_tool_broker import ScopedToolBroker, ToolContext, ToolDefinition


def make_broker(calls):
    def lookup(context, arguments):
        calls.append((context.tenant_id, context.application_id, dict(arguments)))
        return {"value": "trusted-result"}

    return ScopedToolBroker([ToolDefinition(
        tool_id="tool.lookup",
        capability="tool.lookup",
        description="Look up an approved record",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "maxLength": 80}},
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=lookup,
    )])


def test_tool_permissions_are_intersection_not_union():
    broker = make_broker([])
    assert broker.schemas(
        manifest_tools={"tool.lookup"}, application_grants={"tool.lookup"},
        owner_policy={"tool.lookup"}, worker_capabilities={"tool.lookup"},
    )
    assert broker.schemas(
        manifest_tools={"tool.lookup"}, application_grants={"tool.lookup"},
        owner_policy=set(), worker_capabilities={"tool.lookup"},
    ) == []


def test_execution_requires_every_permission_boundary():
    calls = []
    broker = make_broker(calls)
    context = ToolContext("tenant-a", "app-a", "exec-a", "principal-a")
    with pytest.raises(PermissionError):
        broker.execute(
            "tool.lookup", {"query": "hello"}, context=context,
            manifest_tools={"tool.lookup"}, application_grants={"tool.lookup"},
            owner_policy=set(), worker_capabilities={"tool.lookup"},
        )
    assert calls == []


def test_execution_validates_arguments_and_passes_scoped_context():
    calls = []
    broker = make_broker(calls)
    context = ToolContext("tenant-a", "app-a", "exec-a", "principal-a")
    grants = {
        "manifest_tools": {"tool.lookup"},
        "application_grants": {"tool.lookup"},
        "owner_policy": {"tool.lookup"},
        "worker_capabilities": {"tool.lookup"},
    }
    result = broker.execute("tool.lookup", {"query": "hello"}, context=context, **grants)
    assert result == {"value": "trusted-result"}
    assert calls == [("tenant-a", "app-a", {"query": "hello"})]
    with pytest.raises(ValueError):
        broker.execute("tool.lookup", {"query": "x" * 81}, context=context, **grants)
    with pytest.raises(ValueError):
        broker.execute("tool.lookup", {"query": "ok", "extra": True}, context=context, **grants)


def test_unregistered_tools_and_unsafe_schemas_fail_closed():
    with pytest.raises(ValueError):
        ScopedToolBroker([ToolDefinition(
            "tool.bad", "tool.bad", "bad",
            {"type": "object", "properties": {}, "additionalProperties": True},
            lambda _context, _arguments: None,
        )])


def test_provider_safe_function_name_maps_back_to_internal_tool_id():
    broker = make_broker([])
    schemas = broker.schemas(
        manifest_tools={"tool.lookup"}, application_grants={"tool.lookup"},
        owner_policy={"tool.lookup"}, worker_capabilities={"tool.lookup"},
    )
    assert schemas[0]["function"]["name"] == "tool_lookup"
    assert broker.resolve_tool_id("tool_lookup") == "tool.lookup"
    assert broker.resolve_tool_id("tool.unknown") is None


def test_duplicate_provider_function_names_are_rejected():
    def handler(_context, _arguments):
        return None
    schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    with pytest.raises(ValueError, match="Duplicate provider tool function name"):
        ScopedToolBroker([
            ToolDefinition("tool.a", "tool.a", "A", schema, handler),
            ToolDefinition("tool_a", "tool_a", "B", schema, handler),
        ])
