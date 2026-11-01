#!/usr/bin/env python3
"""Verify real local Ollama inference and an already-authorized sandboxed tool call."""
from __future__ import annotations

import os
from urllib.parse import urlsplit

import httpx

from core.plugins import PluginRegistry
from core.store import ArcStore


def main() -> None:
    model = os.environ.get("ORACLE_ARC_MODEL", "qwen2.5:7b").strip()
    ollama = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    parsed = urlsplit(ollama)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Refusing non-loopback Ollama endpoint: local inference must be verified on this host.")
    with httpx.Client(timeout=300.0) as client:
        tags_response = client.get(ollama + "/api/tags")
        tags_response.raise_for_status()
        models = tags_response.json().get("models", [])
        names = {item.get("name") for item in models if isinstance(item, dict)}
        if model not in names:
            raise SystemExit(f"Configured model {model!r} is not pulled into this Ollama instance.")
        inference = client.post(ollama + "/api/chat", json={
            "model": model, "stream": False,
            "messages": [{"role": "user", "content": "Reply with exactly: LOCAL_OLLAMA_INFERENCE_OK"}],
            "options": {"temperature": 0},
        })
        inference.raise_for_status()
        response = inference.json().get("message", {}).get("content", "")
        if not isinstance(response, str) or not response.strip():
            raise SystemExit("Ollama returned an empty inference response.")
        print("PASS: actual local Ollama model is pulled and returned a response.")

    api_key = os.environ.get("ORACLE_ARC_API_KEY", "").strip()
    api_base = os.environ.get("ORACLE_ARC_API_BASE", "http://127.0.0.1:8090").rstrip("/")
    if len(api_key) < 32:
        raise SystemExit("Set ORACLE_ARC_API_KEY to the running Oracle Arc server secret.")
    store = ArcStore(os.environ.get("ORACLE_ARC_DB_PATH", "data/oracle_arc.sqlite3"))
    registry = PluginRegistry()
    approved = store.approved_tools(registry.tool_fingerprints)
    if "calculate" not in approved:
        raise SystemExit("The calculator tool is not currently owner-approved; no approval was changed.")
    before = store.list_tool_audit(500)
    before_ids = {item["id"] for item in before}
    with httpx.Client(timeout=360.0) as client:
        result = client.post(api_base + "/v1/chat/completions",
            headers={"Authorization": "Bearer " + api_key},
            json={"messages": [{"role": "user", "content":
                "You must use the approved calculate tool to compute 17 * 19. "
                "Do not calculate mentally. After the tool returns, report its result."}],
                "max_steps": 4})
        result.raise_for_status()
        answer = result.json()["choices"][0]["message"]["content"]
    after = store.list_tool_audit(500)
    executions = [item for item in after
                  if item["id"] not in before_ids and item["tool_name"] == "calculate"
                  and item["outcome"] == "executed"]
    if not executions:
        raise SystemExit("The live chat did not produce a successful authorized calculator execution.")
    print("PASS: Oracle Arc completed a local-model chat with an owner-approved isolated calculator tool.")
    print("Tool audit event:", executions[0]["id"])
    print("Assistant response:", answer[:500])


if __name__ == "__main__":
    main()
