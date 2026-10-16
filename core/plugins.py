"""Plugin loader and registry."""
import importlib.util
import inspect
from pathlib import Path
from typing import Dict, List, Callable, Any, Optional

class PluginRegistry:
    def __init__(self, plugins_dir: str = "plugins"):
        self.plugins_dir = Path(plugins_dir)
        self.plugins: Dict[str, Dict] = {}
        self.tools: List[Dict] = []
        self.handlers: Dict[str, Callable] = {}
        self.load_all()

    def load_all(self):
        if not self.plugins_dir.exists():
            self.plugins_dir.mkdir(parents=True, exist_ok=True)
            return

        for file in self.plugins_dir.glob("*.py"):
            if file.name.startswith("_"):
                continue
            self._load_plugin(file)

    def _load_plugin(self, path: Path):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if not spec or not spec.loader:
            return
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        plugin = getattr(module, "PLUGIN", None)
        if not plugin or not isinstance(plugin, dict):
            return

        name = plugin.get("name", path.stem)
        self.plugins[name] = plugin

        for tool in plugin.get("tools", []):
            tool_name = tool["name"]
            self.tools.append(tool)
            # Look for handler function with same name
            handler = getattr(module, tool_name, None)
            if handler and callable(handler):
                self.handlers[tool_name] = handler

    def get_tools_schema(self) -> List[Dict]:
        """Return OpenAI-compatible tool schemas for Ollama."""
        schemas = []
        for tool in self.tools:
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
                }
            })
        return schemas

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        handler = self.handlers.get(tool_name)
        if not handler:
            return f"Error: No handler found for tool '{tool_name}'"
        try:
            result = handler(**arguments)
            return str(result)
        except Exception as e:
            return f"Error executing {tool_name}: {e}"
