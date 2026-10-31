"""Allowlisted plugin registry with a fail-closed container execution boundary."""
from __future__ import annotations

import importlib
import json
import os
import subprocess
from typing import Any, Callable

BUILTIN_PLUGIN_MODULES = ("plugins.calculator",)


def run_isolated_worker(arguments: dict[str, Any]) -> dict[str, Any]:
    """Run a one-shot worker in a locked-down rootless Podman container.

    Rootless Podman and the prebuilt worker image must be available to the service.
    Missing runtime/image fails closed; no in-process execution fallback exists.
    """
    image = os.environ.get("ORACLE_ARC_PLUGIN_WORKER_IMAGE", "oracle-arc-plugin-worker:local").strip()
    if not image or any(ch.isspace() for ch in image):
        raise RuntimeError("Invalid worker image configuration")
    runtime = os.environ.get("ORACLE_ARC_PLUGIN_RUNTIME", "podman").strip()
    if runtime != "podman":
        raise RuntimeError("Only rootless Podman is supported for plugin workers")
    command = [
        runtime, "run", "--rm", "--interactive", "--pull=never",
        "--network=none", "--ipc=none",
        "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=16", "--memory=128m", "--memory-swap=128m",
        "--cpus=0.5", "--user=65534:65534",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m",
        "--ulimit=nofile=32:32",
        image,
    ]
    completed = subprocess.run(
        command, input=json.dumps(arguments), text=True,
        capture_output=True, timeout=5, check=False,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", ""),
            "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", ""),
        },
    )
    if completed.returncode != 0:
        raise RuntimeError("Isolated plugin worker failed")
    result = json.loads(completed.stdout)
    if not isinstance(result, dict) or "result" not in result:
        raise RuntimeError("Invalid isolated worker response")
    return result


class PluginRegistry:
    def __init__(self, plugins_dir: str = "plugins",
                 worker_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None):
        self.plugins = {}
        self.tools = []
        self.handlers: dict[str, Callable[..., Any]] = {}
        self.worker_runner = worker_runner or run_isolated_worker
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
        return [{"type": "function", "function": {
            "name": tool["name"], "description": tool.get("description", ""),
            "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
        }} for tool in self.tools]

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name not in self.handlers:
            return "Error: Tool is not in the trusted built-in allowlist"
        if not isinstance(arguments, dict):
            return "Error: Tool arguments must be a JSON object"
        tool = next((item for item in self.tools if item["name"] == tool_name), None)
        if tool is None:
            return "Error: Tool manifest is unavailable"
        schema = tool.get("parameters", {})
        required, properties = schema.get("required", []), schema.get("properties", {})
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
        if tool_name != "calculate":
            return "Error: This built-in has no isolated worker"
        try:
            result = self.worker_runner(arguments)
            return "Result: " + str(result["result"])
        except (subprocess.TimeoutExpired, OSError, ValueError, RuntimeError, KeyError, TypeError):
            return "Error: Isolated plugin worker unavailable or failed"
