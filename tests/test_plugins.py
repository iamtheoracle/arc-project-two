import json
import subprocess

from core.plugins import PluginRegistry, run_isolated_worker


def test_runtime_loads_only_explicit_trusted_builtin_allowlist():
    registry = PluginRegistry(plugins_dir="/tmp/untrusted-plugin-directory")
    names = {tool["name"] for tool in registry.tools}
    assert names == {"calculate"}
    assert "read_file" not in names
    assert "system_info" not in names


def test_runtime_rejects_unexpected_tool_arguments():
    registry = PluginRegistry(worker_runner=lambda args: {"result": 2})
    result = registry.execute("calculate", {"expression": "1 + 1", "unexpected": "value"})
    assert result == "Error: Unexpected tool arguments"


def test_runtime_rejects_non_object_arguments():
    registry = PluginRegistry(worker_runner=lambda args: {"result": 2})
    assert registry.execute("calculate", []) == "Error: Tool arguments must be a JSON object"


def test_calculator_uses_worker_runner():
    registry = PluginRegistry(worker_runner=lambda args: {"result": 15.0})
    assert registry.execute("calculate", {"expression": "sqrt(81) + 3 * 2"}) == "Result: 15.0"


def test_worker_failure_fails_closed():
    def unavailable(_arguments):
        raise RuntimeError("docker daemon unavailable")
    registry = PluginRegistry(worker_runner=unavailable)
    assert registry.execute("calculate", {"expression": "1 + 1"}).startswith("Error:")


def test_docker_worker_uses_restrictive_runtime_flags(monkeypatch):
    seen = {}
    class Completed:
        returncode = 0
        stdout = '{"result": 42}'
    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return Completed()
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert run_isolated_worker({"expression": "6 * 7"}) == {"result": 42}
    command = seen["command"]
    assert command[0] == "podman"
    for flag in ("--network=none", "--read-only", "--cap-drop=ALL",
                 "--security-opt=no-new-privileges", "--pids-limit=16",
                 "--memory=128m", "--memory-swap=128m", "--cpus=0.5",
                 "--user=65534:65534", "--ipc=none"):
        assert flag in command
    assert seen["kwargs"]["timeout"] == 5
    assert seen["kwargs"]["check"] is False


def test_worker_rejects_unsafe_calculator_expression():
    # The worker parser remains the only place where calculator expressions execute.
    from pathlib import Path
    worker = Path("core/plugin_worker.py")
    completed = subprocess.run(
        ["python", str(worker)],
        input=json.dumps({"expression": "__import__('os').getcwd()"}),
        text=True, capture_output=True, timeout=3, check=False,
    )
    assert completed.returncode != 0
    assert "error" in json.loads(completed.stdout)
