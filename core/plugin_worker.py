"""Restricted calculator worker process for a rootless, no-network Podman container."""
from __future__ import annotations

import ast
import json
import math
import operator
import sys

def apply_resource_limits():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
        resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
        if hasattr(resource, "RLIMIT_AS"):
            resource.setrlimit(resource.RLIMIT_AS, (268435456, 268435456))
    except (ImportError, AttributeError, OSError, ValueError):
        pass


OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}
MAX_INPUT_BYTES = 4096
MAX_EXPRESSION_LENGTH = 512
MAX_AST_NODES = 64
MAX_AST_DEPTH = 12
MAX_ABS_VALUE = 10**18
MAX_EXPONENT = 12


def bounded_number(value):
    if type(value) not in (int, float):
        raise ValueError("Only real numeric values are supported")
    if not math.isfinite(value) or abs(value) > MAX_ABS_VALUE:
        raise ValueError("Numeric value exceeds the safe range")
    return value


def validate_tree(tree):
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise ValueError("Expression is too complex")

    def check_depth(node, current=0):
        if current > MAX_AST_DEPTH:
            raise ValueError("Expression is too deeply nested")
        for child in ast.iter_child_nodes(node):
            check_depth(child, current + 1)

    check_depth(tree)


def evaluate(node):
    if isinstance(node, ast.Constant):
        return bounded_number(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        left, right = bounded_number(evaluate(node.left)), bounded_number(evaluate(node.right))
        if isinstance(node.op, ast.Pow) and (abs(right) > MAX_EXPONENT or abs(left) > 1_000_000):
            raise ValueError("Exponentiation exceeds the safe limit")
        return bounded_number(OPS[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return bounded_number(OPS[type(node.op)](evaluate(node.operand)))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.keywords or len(node.args) != 1:
            raise ValueError("Only single-argument sqrt() and abs() calls are supported")
        value = bounded_number(evaluate(node.args[0]))
        if node.func.id == "sqrt":
            if value < 0:
                raise ValueError("sqrt() requires a non-negative value")
            return bounded_number(math.sqrt(value))
        if node.func.id == "abs":
            return bounded_number(abs(value))
    raise ValueError("Unsupported expression")


def execute_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {"expression"}:
        raise ValueError("Invalid worker payload")
    expression = payload["expression"]
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("A mathematical expression is required")
    if len(expression.encode("utf-8")) > MAX_EXPRESSION_LENGTH:
        raise ValueError("Expression exceeds the maximum length")
    tree = ast.parse(expression, mode="eval")
    validate_tree(tree)
    return evaluate(tree.body)


def main():
    apply_resource_limits()
    raw = sys.stdin.read(MAX_INPUT_BYTES + 1)
    if len(raw.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("Worker input exceeds the maximum length")
    payload = json.loads(raw)
    try:
        result = execute_payload(payload)
        print(json.dumps({"result": result}, separators=(",", ":"), allow_nan=False))
    except (ValueError, ArithmeticError, TypeError, OverflowError):
        # A rejected expression is a failed tool call, never a successful result.
        print(json.dumps({"error": "Calculation failed"}))
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("worker_failure=" + type(exc).__name__, file=sys.stderr)
        print(json.dumps({"error": "Calculation failed"}))
        sys.exit(1)
