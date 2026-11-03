"""Bounded, non-eval calculator plugin."""
import ast
import math
import operator

PLUGIN = {
    "name": "calculator",
    "description": "Evaluate bounded mathematical expressions without Python eval.",
    "tools": [{
        "name": "calculate",
        "description": "Evaluate basic arithmetic, powers, sqrt(), and abs().",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string", "minLength": 1, "maxLength": 256}},
            "required": ["expression"],
            "additionalProperties": False,
        },
    }],
}

_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCTIONS = {"sqrt": math.sqrt, "abs": abs}
_MAX_NODES = 64
_MAX_ABS = 10**100


def _bounded(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Only numeric expressions are supported")
    if not math.isfinite(value) or abs(value) > _MAX_ABS:
        raise ValueError("Result is outside the supported numeric range")
    return value


def _evaluate(node):
    if isinstance(node, ast.Constant):
        return _bounded(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 10**6):
            raise ValueError("Exponent is outside the supported range")
        return _bounded(_BINARY[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _bounded(_UNARY[type(node.op)](_evaluate(node.operand)))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = _FUNCTIONS.get(node.func.id)
        if fn is None or node.keywords or len(node.args) != 1:
            raise ValueError("Unsupported function call")
        return _bounded(fn(_evaluate(node.args[0])))
    raise ValueError("Unsupported expression")


def calculate(expression: str) -> str:
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 256:
        return "Calculation error: expression must contain 1 to 256 characters."
    try:
        tree = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > _MAX_NODES:
            raise ValueError("Expression is too complex")
        result = _evaluate(tree.body)
        return f"Result: {result}"
    except (ArithmeticError, SyntaxError, TypeError, ValueError, OverflowError):
        return "Calculation error: unsupported or out-of-range expression."
