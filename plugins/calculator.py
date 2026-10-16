"""Safe calculator plugin."""
import ast
import operator

PLUGIN = {
    "name": "calculator",
    "description": "Precise mathematical calculations and expression evaluation",
    "tools": [
        {
            "name": "calculate",
            "description": "Safely evaluate a mathematical expression. Supports +, -, *, /, **, %, parentheses, and common functions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Math expression to evaluate, e.g. '2 ** 10 + sqrt(16)'"
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

def _safe_eval(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BinOp):
        return SAFE_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        return SAFE_OPS[type(node.op)](_safe_eval(node.operand))
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            fn = node.func.id
            if fn == "sqrt":
                import math
                return math.sqrt(_safe_eval(node.args[0]))
            if fn == "abs":
                return abs(_safe_eval(node.args[0]))
    raise ValueError("Unsupported expression")

def calculate(expression: str) -> str:
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree.body)
        return f"Result: {result}"
    except Exception as e:
        return f"Calculation error: {e}"
