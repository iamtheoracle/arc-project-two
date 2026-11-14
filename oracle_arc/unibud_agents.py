"""Explicit, read-only registration of the UNIBUD 51-agent catalogue in Oracle Arc."""
from __future__ import annotations

import bz2
import hashlib
import json
import re
from pathlib import Path

from .agents import AgentSpec
from .types import Risk

_NAMESPACE = "unibud:"
_MANIFEST_SHA256 = "93c3c862d84ad0801bcd066f16fec9a22dedb69beb32f257f56ef7ab11228652"
_COUNTS = {"core": 16, "specialist": 10, "service": 25}
_DEFAULT = Path(__file__).resolve().parent / "agent_catalogues" / "unibud-51.json.bz2"
_ID = re.compile(r"^[a-z][a-z0-9_]*$")


def _definitions(path: str | Path | None = None) -> list[dict]:
    source = Path(path) if path is not None else _DEFAULT
    try:
        raw = source.read_bytes()
        if source.suffix == ".bz2":
            if hashlib.sha256(raw).hexdigest() != _MANIFEST_SHA256:
                raise ValueError("manifest checksum mismatch")
            raw = bz2.decompress(raw)
        items = json.loads(raw.decode("utf-8"))
    except (OSError, EOFError, UnicodeError, ValueError) as exc:
        raise ValueError(f"cannot load UNIBUD agent manifest: {source}") from exc
    if not isinstance(items, list) or len(items) != 51:
        raise ValueError("UNIBUD agent manifest must contain exactly 51 definitions")

    ids: set[str] = set()
    counts = dict.fromkeys(_COUNTS, 0)
    required = ("id", "name", "category", "role", "mission")
    lists = ("duties", "mustKnowBeforeRouting", "mustNotAssume", "capabilities", "boundaries", "collaborators")
    for item in items:
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip() for k in required):
            raise ValueError("agent definition has missing or invalid identity fields")
        if any(not isinstance(item.get(k), list) or not all(isinstance(v, str) and v.strip() for v in item[k]) for k in lists):
            raise ValueError(f"agent {item['id']} has invalid list fields")
        agent_id, category = item["id"], item["category"]
        if not _ID.fullmatch(agent_id) or agent_id in ids or category not in counts:
            raise ValueError(f"invalid or duplicate agent identity/category: {agent_id}")
        ids.add(agent_id)
        counts[category] += 1
    if counts != _COUNTS:
        raise ValueError(f"agent category counts mismatch: {counts}")
    for item in items:
        collaborators = set(item["collaborators"])
        if item["id"] in collaborators or not collaborators <= ids:
            raise ValueError(f"invalid collaborator references for {item['id']}")
    return items


def _prompt(item: dict) -> str:
    lines = [
        f"You are {item['name']}, the {item['role']} in the UNIBUD application agent catalogue.",
        f"Mission: {item['mission']}",
        f"Duties: {'; '.join(item['duties'])}.",
        f"Required context: {'; '.join(item['mustKnowBeforeRouting'])}.",
        f"Do not assume: {'; '.join(item['mustNotAssume'])}.",
        f"Boundaries: {'; '.join(item['boundaries'])}.",
        "Declared capabilities (metadata only; not connected by this host registration): " + ", ".join(item["capabilities"]),
        "Do not claim providers, records, actions, or outcomes without evidence from a separately authorized and verified host tool.",
        "Collaborators are catalogue metadata only; this registration grants no delegation or autonomous orchestration.",
        "No SPARK memory namespace, tools, or grants are provided. Use only information in the current authorized request.",
    ]
    distinctions = {
        "spark": "UNIBUD Spark is namespaced as unibud:spark and is not Oracle Arc SPARK, which remains user-controlled memory.",
        "oracle": "UNIBUD Oracle is namespaced as unibud:oracle and is separate from Oracle Arc ORACLE.",
        "orbit": "UNIBUD Orbit is namespaced as unibud:orbit and is separate from Oracle Arc ORBITS media processing.",
    }
    if item["id"] in distinctions:
        lines.append(distinctions[item["id"]])
    return "\n".join(lines)


def load_unibud_agent_specs(manifest_path: str | Path | None = None) -> tuple[AgentSpec, ...]:
    """Return 51 namespaced, read-only AgentSpecs; never creates tools, grants, or memory access."""
    return tuple(
        AgentSpec(
            name=f"{_NAMESPACE}{item['id']}", version="1.0.0",
            role=f"UNIBUD {item['name']} — {item['role']}", system_prompt=_prompt(item),
            max_risk=Risk.READ, memory_namespaces=(),
        )
        for item in _definitions(manifest_path)
    )
