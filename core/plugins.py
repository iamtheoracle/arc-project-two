"""Explicit allowlist for trusted built-in tools.

Arbitrary files in the plugins directory are never discovered or imported. Built-ins still
run in the API process; they are not a security sandbox and must remain narrowly scoped.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


# Only reviewed, repository-owned modules may be loaded here. Do not add third-party
# or user-uploaded modules until an isolated worker execution boundary exists.
BUILTIN_PLUGIN_MODULES = ("plugins.calculator",)


class PluginRegistry:
    def __init__(self, plugins_dir: str = "plugins"):
        self.plugins = {}
        self.tools = []
        self.handlers: dict[str, Callable[..., Any]] = {}
        self.load_all()

    def load_all(self):
        for module_name in BUILTIN_PLUGIN_MODULES:
            module = importlib.import_module(module_name)
            plugin = getattr(module, "PLUGIN", None)
            if not isinstance(plugin, dict):
                continue
            plugin_name = plugin.get("name")
            if not isinstance(plugin_name, str) or not plugin_name:
                continue
            self.plugins[plugin_name] = plugin
            for tool in plugin.get("tools", []):
                if not isinstance(tool, dict):
                    continue
                tool_name = tool.get("name")
                if not isinstance(tool_name, str) or not tool_name:
                    continue
                if tool_name in self.handlers:
                    raise ValueError("Duplicate built-in tool name")
                handler = getattr(module, tool_name, None)
                if callable(handler):
                    self.tools.append(tool)
                    self.handlers[tool_name] = handler

    def get_tools_schema(self):
        schemas = []
        for tool in self.tools:
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {
                        "type": "object", "properties": {},
                    }),
                },
            })
        return schemas

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        handler = self.handlers.get(tool_name)
        if handler is None:
            return "Error: Tool is not in the trusted built-in allowlist"
        if not isinstance(arguments, dict):
            return "Error: Tool arguments must be a JSON object"
        tool = next((item for item in self.tools if item["name"] == tool_name), None)
        if tool is None:
            return "Error: Tool manifest is unavailable"
        schema = tool.get("parameters", {})
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        if any(key not in arguments for key in required):
            return "Error: Required tool arguments are missing"
        if any(key not in properties for key in arguments):
            return "Error: Unexpected tool arguments"
        for key, value in arguments.items():
            expected = properties.get(key, {}).get("type")
            valid = {
                "string": lambda v: isinstance(v, str),
                "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
                "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
                "boolean": lambda v: isinstance(v, bool),
                "object": lambda v: isinstance(v, dict),
                "array": lambda v: isinstance(v, list),
            }.get(expected)
            if valid and not valid(value):
                return "Error: Tool argument type is invalid"
        try:
            if tool_name == "calculate":
                worker = Path(__file__).with_name("plugin_worker.py")
                completed = subprocess.run(
                    [sys.executable, "-I", str(worker)],
                    input=json.dumps(arguments),
                    text=True,
                    capture_output=True,
                    timeout=3,
                    cwd=tempfile.gettempdir(),
                    env={"PYTHONIOENCODING": "utf-8"},
                    check=False,
                )
                if completed.returncode != 0:
                    return "Error: Isolated plugin worker rejected or failed the request"
                result = json.loads(completed.stdout)
                if "result" not in result:
                    return "Error: Isolated plugin worker returned no result"
                return "Result: " + str(result["result"])
            return "Error: This built-in has no isolated worker"
        except (subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError):
            return "Error: Isolated plugin worker failed"
