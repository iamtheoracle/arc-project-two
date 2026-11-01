import pytest

from core.platform_tools import (
    PlatformToolRegistry, ToolDescriptor, ToolUnavailable, default_tool_registry,
)


def test_calculator_handles_bounded_arithmetic():
    registry = default_tool_registry()
    assert registry.execute(
        "math.calculate", {"expression": "(12 + 8) * 3 / 2"},
        allowed_tools=["math.calculate"], classification="private",
    ) == {"result": 30}


@pytest.mark.parametrize("expression", [
    "__import__('os').system('id')",
    "open('/etc/passwd').read()",
    "x + 1",
    "1 .__class__",
    "[x for x in (1, 2)]",
    "lambda: 1",
    "1[0]",
])
def test_calculator_rejects_code_and_non_arithmetic_syntax(expression):
    registry = default_tool_registry()
    with pytest.raises(ValueError):
        registry.execute(
            "math.calculate", {"expression": expression},
            allowed_tools=["math.calculate"], classification="private",
        )


def test_calculator_enforces_manifest_classification_and_size():
    registry = default_tool_registry()
    with pytest.raises(PermissionError):
        registry.execute("math.calculate", {"expression": "1+1"},
                         allowed_tools=[], classification="private")
    with pytest.raises(PermissionError):
        registry.execute("math.calculate", {"expression": "1+1"},
                         allowed_tools=["math.calculate"], classification="restricted")
    with pytest.raises(ValueError):
        registry.execute("math.calculate", {"expression": "1" * 300},
                         allowed_tools=["math.calculate"], classification="private")


def test_registry_rejects_unknown_tools_and_duplicate_installation():
    registry = default_tool_registry()
    with pytest.raises(ToolUnavailable):
        registry.get("network.fetch")
    descriptor = ToolDescriptor(
        tool_id="math.calculate", version="1.0.0", description="duplicate",
        input_schema={"type": "object"}, required_capability="math.calculate",
        allowed_classifications=("public",),
    )
    with pytest.raises(ValueError):
        registry.install(descriptor, lambda args: {"result": 0})


def test_model_tool_definitions_are_derived_only_from_installed_grants():
    registry = default_tool_registry()
    definitions = registry.definitions(["math.calculate"], "internal")
    assert definitions[0]["function"]["name"] == "math.calculate"
    with pytest.raises(ToolUnavailable):
        registry.definitions(["network.fetch"], "internal")
