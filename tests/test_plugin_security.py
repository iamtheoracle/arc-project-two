import json

from core.plugins import PluginRegistry
from plugins.calculator import calculate


def test_plugins_are_not_imported_without_explicit_trust(tmp_path):
    marker = tmp_path / "imported.txt"
    (tmp_path / "dangerous.py").write_text(
        "from pathlib import Path\n"
        + "Path(" + repr(str(marker)) + ").write_text('executed')\n"
        + "PLUGIN = {'name':'dangerous','tools':[]}\n",
        encoding="utf-8",
    )
    registry = PluginRegistry(str(tmp_path), trusted_plugins=set())
    assert registry.tools == []
    assert not marker.exists()


def test_only_allowlisted_plugin_is_loaded(tmp_path):
    (tmp_path / "safe.py").write_text(
        "PLUGIN = {'name':'safe','tools':[{'name':'echo','description':'Echo text',"
        "'parameters':{'type':'object','properties':{'text':{'type':'string'}},"
        "'required':['text'],'additionalProperties':False}}]}\n"
        "def echo(text): return text\n",
        encoding="utf-8",
    )
    registry = PluginRegistry(str(tmp_path), trusted_plugins={"safe"})
    assert [tool["name"] for tool in registry.tools] == ["echo"]
    assert registry.execute("echo", {"text": "hello"}) == "hello"
    assert registry.execute("echo", {"text": "hello", "extra": "no"}) == (
        "Error: tool arguments did not match the approved schema."
    )


def test_plugin_execution_errors_do_not_leak_exception_details(tmp_path):
    (tmp_path / "broken.py").write_text(
        "PLUGIN = {'name':'broken','tools':[{'name':'explode','description':'Explode',"
        "'parameters':{'type':'object','properties':{}}}]}\n"
        "def explode(): raise RuntimeError('secret path /private/key')\n",
        encoding="utf-8",
    )
    registry = PluginRegistry(str(tmp_path), trusted_plugins={"broken"})
    result = registry.execute("explode", {})
    assert result == "Error: approved tool execution failed."
    assert "/private/key" not in result


def test_calculator_rejects_unsafe_and_unbounded_expressions():
    assert calculate("2 ** 10") == "Result: 1024"
    assert calculate("__import__('os').system('id')").startswith("Calculation error:")
    assert calculate("9 ** 999999").startswith("Calculation error:")
    assert calculate("sqrt(16)") == "Result: 4.0"
    assert calculate("sqrt(16, 2)").startswith("Calculation error:")
