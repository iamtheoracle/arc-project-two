from core.plugins import PluginRegistry


def test_runtime_loads_only_explicit_trusted_builtin_allowlist():
    registry = PluginRegistry(plugins_dir="/tmp/untrusted-plugin-directory")
    names = {tool["name"] for tool in registry.tools}
    assert names == {"calculate"}
    assert "read_file" not in names
    assert "system_info" not in names


def test_runtime_rejects_unexpected_tool_arguments():
    registry = PluginRegistry()
    result = registry.execute("calculate", {"expression": "1 + 1", "unexpected": "value"})
    assert result == "Error: Unexpected tool arguments"


def test_runtime_rejects_non_object_arguments():
    registry = PluginRegistry()
    assert registry.execute("calculate", []) == "Error: Tool arguments must be a JSON object"

def test_calculator_runs_in_separate_restricted_worker():
    registry = PluginRegistry()
    assert registry.execute("calculate", {"expression": "sqrt(81) + 3 * 2"}) == "Result: 15.0"


def test_worker_rejects_unsafe_calculator_expression():
    registry = PluginRegistry()
    result = registry.execute("calculate", {"expression": "__import__('os').getcwd()"})
    assert result.startswith("Error:")
