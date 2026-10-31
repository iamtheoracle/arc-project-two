"""Allowlisted plugin registry. Importing a plugin executes Python code, so trust is explicit."""
from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any, Callable


_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


class PluginRegistry:
    def __init__(self, plugins_dir: str = "plugins", trusted_plugins: set[str] | None = None):
        self.plugins_dir = Path(plugins_dir).resolve()
        configured = os.environ.get("ORACLE_ARC_TRUSTED_PLUGINS", "")
        self.trusted_plugins = set(trusted_plugins) if trusted_plugins is not None else {
            item.strip() for item in configured.split(",") if item.strip()
        }
        self.plugins: dict[str, dict] = {}
        self.tools: list[dict] = []
        self.handlers: dict[str, Callable] = {}
        self.load_all()

    def load_all(self) -> None:
        # No Python plugin is imported unless its filename stem has been explicitly
        # reviewed and allowlisted by the owner in the trusted server environment.
        if not self.plugins_dir.exists():
            return
        seen_tools: set[str] = set()
        for path in sorted(self.plugins_dir.glob("*.py")):
            if path.name.startswith("_") or path.stem not in self.trusted_plugins:
                continue
            resolved = path.resolve()
            if resolved.parent != self.plugins_dir or not resolved.is_file():
                continue
            self._load_plugin(resolved, seen_tools)

    def _load_plugin(self, path: Path, seen_tools: set[str]) -> None:
        if not _NAME.fullmatch(path.stem):
            return
        try:
            spec = importlib.util.spec_from_file_location(f"oracle_arc_plugin_{path.stem}", path)
            if not spec or not spec.loader:
                return
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            plugin = getattr(module, "PLUGIN", None)
            if not isinstance(plugin, dict):
                return
            plugin_name = plugin.get("name", path.stem)
            if not isinstance(plugin_name, str) or not _NAME.fullmatch(plugin_name):
                return
            raw_tools = plugin.get("tools", [])
            if not isinstance(raw_tools, list):
                return
            accepted: list[dict] = []
            for tool in raw_tools:
                if not isinstance(tool, dict):
                    continue
                name = tool.get("name")
                description = tool.get("description")
                parameters = tool.get("parameters", {"type": "object", "properties": {}})
                handler = getattr(module, name, None) if isinstance(name, str) else None
                if (not isinstance(name, str) or not _NAME.fullmatch(name) or name in seen_tools
                        or not isinstance(description, str) or not description.strip()
                        or not isinstance(parameters, dict) or parameters.get("type") != "object"
                        or not callable(handler)):
                    continue
                accepted.append({"name": name, "description": description[:1000], "parameters": parameters})
                self.handlers[name] = handler
                seen_tools.add(name)
            if accepted:
                self.plugins[plugin_name] = {"name": plugin_name, "tools": accepted}
                self.tools.extend(accepted)
        except Exception:
            # Do not leak plugin import exceptions or abort the whole assistant startup.
            return

    def get_tools_schema(self) -> list[dict]:
        return [{
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        } for tool in self.tools]

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name not in self.handlers:
            return "Error: tool is not available in the trusted plugin registry."
        if not isinstance(arguments, dict):
            return "Error: tool arguments must be a JSON object."
        try:
            from jsonschema import Draft202012Validator
            tool = next(item for item in self.tools if item["name"] == tool_name)
            Draft202012Validator.check_schema(tool["parameters"])
            errors = list(Draft202012Validator(tool["parameters"]).iter_errors(arguments))
            if errors:
                return "Error: tool arguments did not match the approved schema."
            result = self.handlers[tool_name](**arguments)
            # Tool output is untrusted and must not be allowed to flood the model context.
            if isinstance(result, (dict, list)):
                rendered = json.dumps(result, ensure_ascii=False, default=str)
            else:
                rendered = str(result)
            return rendered[:12000]
        except Exception:
            # Never expose exception messages, paths, secrets, or tracebacks to the model.
            return "Error: approved tool execution failed."
