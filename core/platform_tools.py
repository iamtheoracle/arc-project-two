"""Platform-installed tool registry for Oracle Arc.

Developer manifests can reference these stable tool IDs, but cannot upload handlers.
The initial calculator is deterministic and has no filesystem, network or process access.
"""
from __future__ import annotations

import ast
import json
import math
import operator
from dataclasses import dataclass
from typing import Any, Callable


class ToolUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolDescriptor:
    tool_id: str
    version: str
    description: str
    input_schema: dict[str, Any]
    required_capability: str
    allowed_classifications: tuple[str, ...]
    max_input_bytes: int = 4096
    max_output_bytes: int = 4096


class PlatformToolRegistry:
    """Registry of code-installed tools; no dynamic imports or user handlers."""

    def __init__(self) -> None:
        self._descriptors: dict[str, ToolDescriptor] = {}
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}

    def install(self, descriptor: ToolDescriptor,
                handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        if (not isinstance(descriptor, ToolDescriptor)
                or not descriptor.tool_id
                or not callable(handler)
                or descriptor.tool_id in self._handlers):
            raise ValueError("Invalid or duplicate platform tool installation")
        if descriptor.required_capability != descriptor.tool_id:
            raise ValueError("Tool capability must exactly match its stable tool ID")
        if descriptor.max_input_bytes < 1 or descriptor.max_output_bytes < 1:
            raise ValueError("Tool input and output bounds must be positive")
        self._descriptors[descriptor.tool_id] = descriptor
        self._handlers[descriptor.tool_id] = handler

    def get(self, tool_id: str) -> ToolDescriptor:
        descriptor = self._descriptors.get(tool_id)
        if descriptor is None:
            raise ToolUnavailable("Requested tool is not installed by the platform")
        return descriptor

    def definitions(self, allowed_tools: list[str], classification: str) -> list[dict[str, Any]]:
        result = []
        for tool_id in allowed_tools:
            descriptor = self.get(tool_id)
            if classification not in descriptor.allowed_classifications:
                raise PermissionError("Tool is not approved for this data classification")
            result.append({
                "type": "function",
                "function": {
                    "name": descriptor.tool_id,
                    "description": descriptor.description,
                    "parameters": descriptor.input_schema,
                },
            })
        return result

    def execute(self, tool_id: str, arguments: Any, *,
                allowed_tools: list[str], classification: str) -> dict[str, Any]:
        descriptor = self.get(tool_id)
        if tool_id not in allowed_tools:
            raise PermissionError("Agent manifest does not grant this tool")
        if classification not in descriptor.allowed_classifications:
            raise PermissionError("Tool is not approved for this data classification")
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")
        encoded = json.dumps(arguments, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) > descriptor.max_input_bytes:
            raise ValueError("Tool input exceeds the installed tool limit")
        result = self._handlers[tool_id](arguments)
        if not isinstance(result, dict):
            raise RuntimeError("Platform tool returned an invalid result")
        output = json.dumps(result, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(output) > descriptor.max_output_bytes:
            raise ValueError("Tool output exceeds the installed tool limit")
        return result


_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _bounded_number(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Calculator accepts numeric values only")
    if not math.isfinite(float(value)) or abs(value) > 1e100:
        raise ValueError("Calculator numeric value is outside supported bounds")
    return value


def _evaluate_node(node: ast.AST) -> int | float:
    if isinstance(node, ast.Expression):
        return _evaluate_node(node.body)
    if isinstance(node, ast.Constant):
        return _bounded_number(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1e10):
            raise ValueError("Exponentiation exceeds calculator limits")
        value = _BINOPS[type(node.op)](left, right)
        return _bounded_number(value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _bounded_number(_UNARYOPS[type(node.op)](_evaluate_node(node.operand)))
    raise ValueError("Calculator expression contains an unsupported operation")


def _calculate(arguments: dict[str, Any]) -> dict[str, Any]:
    if set(arguments) != {"expression"}:
        raise ValueError("Calculator requires exactly one expression field")
    expression = arguments["expression"]
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 256:
        raise ValueError("Expression must be a non-empty string of at most 256 characters")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError) as exc:
        raise ValueError("Invalid calculator expression") from exc
    if sum(1 for _ in ast.walk(tree)) > 64:
        raise ValueError("Calculator expression is too complex")
    try:
        result = _evaluate_node(tree)
    except (ArithmeticError, OverflowError) as exc:
        raise ValueError("Calculator operation is undefined or outside supported limits") from exc
    return {"result": result}


def default_tool_registry() -> PlatformToolRegistry:
    registry = PlatformToolRegistry()
    registry.install(
        ToolDescriptor(
            tool_id="math.calculate",
            version="1.0.0",
            description="Evaluate a bounded arithmetic expression. No variables, functions or external access.",
            input_schema={
                "type": "object",
                "properties": {"expression": {"type": "string", "maxLength": 256}},
                "required": ["expression"],
                "additionalProperties": False,
            },
            required_capability="math.calculate",
            allowed_classifications=("public", "internal", "private"),
        ),
        _calculate,
    )
    return registry
