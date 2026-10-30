"""Restricted calculator worker process. Input and output are one JSON object per run."""
import ast
import json
import math
import operator
import sys

try:
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
    resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
    if hasattr(resource, "RLIMIT_AS"):
        resource.setrlimit(resource.RLIMIT_AS, (268435456, 268435456))
except (ImportError, AttributeError, OSError, ValueError):
    pass

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
       ast.USub: operator.neg, ast.UAdd: operator.pos}
FUNCS = {"sqrt": math.sqrt, "abs": abs}


def evaluate(node):
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        left, right = evaluate(node.left), evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("Exponent limit exceeded")
        return OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return OPS[type(node.op)](evaluate(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS and len(node.args) == 1:
        return FUNCS[node.func.id](evaluate(node.args[0]))
    raise ValueError("Unsupported expression")


def main():
    payload = json.loads(sys.stdin.readline())
    expression = payload.get("expression")
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 500:
        raise ValueError("Invalid expression")
    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 100:
        raise ValueError("Expression is too complex")
    result = evaluate(tree.body)
    if not isinstance(result, (int, float)) or not math.isfinite(result):
        raise ValueError("Result is not finite")
    print(json.dumps({"result": result}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(json.dumps({"error": "Calculation failed"}))
        sys.exit(1)
