"""Trusted, server-registered tools exposed to the platform worker.

The initial production registry deliberately exposes only the existing calculator plugin.
Its implementation runs through the isolated rootless-Podman plugin worker; agent manifests
cannot import code, register handlers, choose executables, or supply a runtime image.
"""
from __future__ import annotations

from core.plugins import PluginRegistry
from core.scoped_tool_broker import ScopedToolBroker, ToolDefinition

PLATFORM_TOOL_IDS = frozenset({"tool.calculate"})


def build_platform_tool_broker(plugin_registry: PluginRegistry | None = None) -> ScopedToolBroker:
    plugins = plugin_registry or PluginRegistry()

    def calculate(_context, arguments):
        result = plugins.execute("calculate", arguments)
        return {"result": result}

    return ScopedToolBroker([
        ToolDefinition(
            tool_id="tool.calculate",
            capability="tool.calculate",
            description="Safely evaluate a bounded mathematical expression in the isolated plugin worker.",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "maxLength": 512},
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
            handler=calculate,
            function_name="tool_calculate",
        ),
    ])
