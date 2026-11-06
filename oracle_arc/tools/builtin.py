"""Built-in read-only tools."""
from __future__ import annotations

import ast
import math
import operator
import re
from pathlib import Path

from ..types import Risk, ToolUnavailable, ValidationError
from .registry import ToolSpec

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
_UN = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_FN = {"sqrt": math.sqrt, "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil,
       "sin": math.sin, "cos": math.cos, "tan": math.tan, "log": math.log, "log10": math.log10, "exp": math.exp}
_CONST = {"pi": math.pi, "e": math.e}
MAX_NODES, MAX_EXP, MAX_ABS = 200, 1000, 1e300


def _ev(node, budget):
    budget[0] -= 1
    if budget[0] < 0:
        raise ValidationError("expression too complex")
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONST:
        return _CONST[node.id]
    if isinstance(node, ast.BinOp):
        l, r = _ev(node.left, budget), _ev(node.right, budget)
        if isinstance(node.op, ast.Pow):
            if abs(r) > MAX_EXP or abs(l) > MAX_ABS:        # blocks 9**9**9 style resource exhaustion
                raise ValidationError("exponent too large")
            out = l ** r
        elif type(node.op) in _BIN:
            out = _BIN[type(node.op)](l, r)
        else:
            raise ValidationError("unsupported operator")
    elif isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
        out = _UN[type(node.op)](_ev(node.operand, budget))
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FN and not node.keywords:
        out = _FN[node.func.id](*[_ev(a, budget) for a in node.args])
    else:
        raise ValidationError("unsupported expression")
    if isinstance(out, complex) or (isinstance(out, float) and (math.isnan(out) or math.isinf(out))):
        raise ValidationError("result is not a finite real number")
    return out


def calculate(expression: str):
    if len(expression) > 300:
        raise ValidationError("expression too long")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError:
        raise ValidationError("could not parse expression") from None
    try:
        return _ev(tree.body, [MAX_NODES])
    except ZeroDivisionError:
        raise ValidationError("division by zero") from None
    except (OverflowError, ValueError) as e:
        raise ValidationError(f"math error: {e}") from None


_CALC_RE = re.compile(r"^\s*(?:what(?:'s| is)\s+|calc(?:ulate)?\s*:?\s*|compute\s+)?([\d\s\.\+\-\*/%\(\)\^,]+|[\w\s\.\+\-\*/%\(\),]*\b(?:sqrt|abs|sin|cos|tan|log|exp|pi)\b[\w\s\.\+\-\*/%\(\),]*)\s*\??\s*$", re.I)


def _calc_match(message: str):
    m = _CALC_RE.match(message)
    if not m:
        return None
    expr = m.group(1).replace("^", "**").strip()
    if not re.search(r"\d", expr) or not re.search(r"[\+\-\*/%]|\*\*|\b(?:sqrt|abs|sin|cos|tan|log|exp)\b", expr):
        return None
    return {"expression": expr}


def calculator_tool() -> ToolSpec:
    return ToolSpec(
        name="calculate", description="Evaluate a mathematical expression exactly.", risk=Risk.READ,
        parameters={"type": "object", "required": ["expression"],
                    "properties": {"expression": {"type": "string", "maxLength": 300}}},
        executor=lambda args, ctx: calculate(args["expression"]),
        verifier=lambda args, res, ctx: res == calculate(args["expression"]),
        match=_calc_match)


def read_file_tool(allowed_roots) -> ToolSpec:
    roots = [Path(r).resolve() for r in allowed_roots]

    def run(args, ctx):
        p = Path(args["path"]).expanduser().resolve()           # resolves symlinks and ..
        if not any(p == r or r in p.parents for r in roots):
            raise ValidationError("path is outside the permitted directories")
        if not p.is_file():
            raise ValidationError("file not found")
        return p.read_text(encoding="utf-8", errors="replace")[: int(args.get("max_chars", 8000))]

    return ToolSpec(
        name="read_file", description="Read a text file from a permitted directory.", risk=Risk.READ,
        parameters={"type": "object", "required": ["path"],
                    "properties": {"path": {"type": "string"},
                                   "max_chars": {"type": "integer", "minimum": 1, "maximum": 50000}}},
        executor=run, verifier=lambda a, r, c: isinstance(r, str))
