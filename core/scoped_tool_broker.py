"""Permission-intersected broker for reviewed, in-process Oracle Arc tools.

This module never imports application code or evaluates agent-supplied code. Handlers
must be registered by trusted server startup code. Every invocation requires the
intersection of manifest, application, owner-policy and worker grants.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class ToolContext:
    tenant_id: str
    application_id: str
    execution_id: str
    principal_id: str


@dataclass(frozen=True)
class ToolDefinition:
    tool_id: str
    capability: str
    description: str
    parameters: Mapping[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], Any]
    function_name: str | None = None


class ScopedToolBroker:
    def __init__(self, tools: list[ToolDefinition] | tuple[ToolDefinition, ...]):
        self._tools: dict[str, ToolDefinition] = {}
        for tool in tools:
            if not isinstance(tool, ToolDefinition):
                raise ValueError("Only reviewed ToolDefinition entries can be registered")
            if not tool.tool_id or not tool.capability or not callable(tool.handler):
                raise ValueError("Tool registration is incomplete")
            function_name = tool.function_name or tool.tool_id
            if not isinstance(function_name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", function_name):
                raise ValueError("Tool function names must use provider-safe characters")
            if tool.tool_id in self._tools:
                raise ValueError("Duplicate tool registration")
            self._validate_schema_definition(tool.parameters)
            self._tools[tool.tool_id] = tool

    @staticmethod
    def _validate_schema_definition(schema: Mapping[str, Any]) -> None:
        if not isinstance(schema, Mapping) or schema.get("type") != "object":
            raise ValueError("Tool parameters must use an object schema")
        if schema.get("additionalProperties", False) is not False:
            raise ValueError("Tool schemas must reject additional properties")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, Mapping) or not isinstance(required, list):
            raise ValueError("Invalid tool schema")
        if len(set(required)) != len(required) or any(k not in properties for k in required):
            raise ValueError("Tool schema required fields must exist in properties")
        supported = {"string", "integer", "number", "boolean"}
        for name, spec in properties.items():
            if not isinstance(name, str) or not isinstance(spec, Mapping) or spec.get("type") not in supported:
                raise ValueError("Only bounded primitive tool arguments are supported")
            if spec["type"] == "string":
                maximum = spec.get("maxLength", 4096)
                if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 100000:
                    raise ValueError("String tool arguments require a safe maxLength")
            if spec["type"] in {"integer", "number"}:
                if "minimum" in spec and "maximum" in spec and spec["minimum"] > spec["maximum"]:
                    raise ValueError("Invalid numeric argument bounds")

    @staticmethod
    def _validate_arguments(schema: Mapping[str, Any], arguments: dict[str, Any]) -> None:
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if any(key not in arguments for key in required):
            raise ValueError("Required tool arguments are missing")
        if any(key not in properties for key in arguments):
            raise ValueError("Unexpected tool argument")
        for key, value in arguments.items():
            spec = properties[key]
            kind = spec["type"]
            valid = {
                "string": lambda x: isinstance(x, str),
                "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
                "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
                "boolean": lambda x: isinstance(x, bool),
            }[kind](value)
            if not valid:
                raise ValueError("Tool argument has the wrong type")
            if kind == "string" and len(value) > spec.get("maxLength", 4096):
                raise ValueError("Tool string argument exceeds its limit")
            if kind in {"integer", "number"}:
                if "minimum" in spec and value < spec["minimum"]:
                    raise ValueError("Tool numeric argument is below its limit")
                if "maximum" in spec and value > spec["maximum"]:
                    raise ValueError("Tool numeric argument exceeds its limit")

    def resolve_tool_id(self, function_name: str) -> str | None:
        for tool in self._tools.values():
            if (tool.function_name or tool.tool_id) == function_name:
                return tool.tool_id
        return None

    def schemas(self, *, manifest_tools: set[str], application_grants: set[str],
                owner_policy: set[str], worker_capabilities: set[str]) -> list[dict[str, Any]]:
        allowed = manifest_tools & application_grants & owner_policy
        return [
            {"type": "function", "function": {
                "name": tool.function_name or tool.tool_id, "description": tool.description,
                "parameters": dict(tool.parameters),
            }}
            for tool in self._tools.values()
            if tool.tool_id in allowed and tool.capability in worker_capabilities
        ]

    def execute(self, tool_id: str, arguments: dict[str, Any], *,
                context: ToolContext, manifest_tools: set[str],
                application_grants: set[str], owner_policy: set[str],
                worker_capabilities: set[str]) -> Any:
        tool = self._tools.get(tool_id)
        if tool is None:
            raise PermissionError("Tool is not in the trusted registry")
        if not (
            tool_id in manifest_tools
            and tool_id in application_grants
            and tool_id in owner_policy
            and tool.capability in worker_capabilities
        ):
            raise PermissionError("Tool is outside the effective execution permission set")
        self._validate_arguments(tool.parameters, arguments)
        # Pass a fresh dict so a handler cannot mutate the caller's argument object.
        return tool.handler(context, dict(arguments))
