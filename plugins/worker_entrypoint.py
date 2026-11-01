"""Minimal stdin/stdout entrypoint for the isolated calculator container."""
from __future__ import annotations

import json
import sys
from typing import Any

from plugins.calculator import calculate

MAX_INPUT_BYTES = 4096


def execute(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict) or set(payload) != {"expression"}:
        raise ValueError("Invalid calculator worker payload")
    expression = payload["expression"]
    if not isinstance(expression, str) or len(expression.encode("utf-8")) > 512:
        raise ValueError("Invalid calculator expression")
    return {"result": calculate(expression)}


def main() -> int:
    raw = sys.stdin.read(MAX_INPUT_BYTES + 1)
    if len(raw.encode("utf-8")) > MAX_INPUT_BYTES:
        print(json.dumps({"error": "input_too_large"}))
        return 2
    try:
        payload = json.loads(raw)
        result = execute(payload)
        print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
        return 0
    except Exception:
        print(json.dumps({"error": "invalid_calculator_request"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
