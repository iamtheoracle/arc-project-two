"""Safe bounded calculator plugin.

The parser accepts a deliberately small arithmetic grammar. Expressions are bounded
before evaluation and every intermediate value is checked to prevent CPU/memory abuse
even when invoked from an otherwise permission-authorized agent.
"""
import ast
import math
import operator

PLUGIN = {
    "name": "calculator",
    "description": "Precise bounded mathematical calculations and expression evaluation",
    "tools": [
        {
            "name": "calculate",
            "description": "Safely evaluate a bounded mathematical expression. Supports +, -, *, /, **, %, parentheses, sqrt() and abs().",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Math expression, e.g. '2 ** 10 + sqrt(16)'"
                    }
                },
                "required": ["expression"]
            }
        }
    ]
}

SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
MAX_EXPRESSION_LENGTH = 512
MAX_AST_NODES = 64
MAX_AST_DEPTH = 12
MAX_ABS_VALUE = 10**18
MAX_EXPONENT = 12


def _bounded_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Only real numeric values are supported")
    if not math.isfinite(value) or abs(value) > MAX_ABS_VALUE:
        raise ValueError("Calculation result exceeds the safe numeric range")
    return value


def _validate_tree(tree):
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        raise ValueError("Expression is too complex")
    def depth(node, current=0):
        if current > MAX_AST_DEPTH:
            raise ValueError("Expression is too deeply nested")
        for child in ast.iter_child_nodes(node):
            depth(child, current + 1)
    depth(tree)


def _safe_eval(node):
    if isinstance(node, ast.Constant):
        return _bounded_number(node.value)
    if isinstance(node, ast.BinOp):
        left = _bounded_number(_safe_eval(node.left))
        right = _bounded_number(_safe_eval(node.right))
        if isinstance(node.op, ast.Pow):
            if abs(right) > MAX_EXPONENT or abs(left) > 1_000_000:
                raise ValueError("Exponentiation exceeds the safe calculation limit")
        result = SAFE_OPS[type(node.op)](left, right)
        return _bounded_number(result)
    if isinstance(node, ast.UnaryOp):
        return _bounded_number(SAFE_OPS[type(node.op)](_safe_eval(node.operand)))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.keywords or len(node.args) != 1:
            raise ValueError("Only single-argument sqrt() and abs() calls are supported")
        value = _bounded_number(_safe_eval(node.args[0]))
        if node.func.id == "sqrt":
            if value < 0:
                raise ValueError("sqrt() requires a non-negative value")
            return _bounded_number(math.sqrt(value))
        if node.func.id == "abs":
            return _bounded_number(abs(value))
    raise ValueError("Unsupported expression")


def calculate(expression: str) -> str:
    try:
        if not isinstance(expression, str) or not expression.strip():
            raise ValueError("A mathematical expression is required")
        if len(expression) > MAX_EXPRESSION_LENGTH:
            raise ValueError("Expression exceeds the maximum length")
        tree = ast.parse(expression, mode="eval")
        _validate_tree(tree)
        result = _safe_eval(tree.body)
        return f"Result: {result}"
    except Exception as exc:
        # Return a bounded error message, never a traceback or environment detail.
        return "Calculation error: " + str(exc)[:160]
