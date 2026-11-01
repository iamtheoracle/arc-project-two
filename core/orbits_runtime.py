"""Fail-closed runner for ORBITS' isolated media processor image."""
from __future__ import annotations

import base64
import json
import os
import subprocess
from typing import Any


def run_isolated_orbits_processor(processor_id: str, data: bytes) -> dict[str, Any]:
    if processor_id not in {"document.extract", "image.ocr", "audio.inspect"}:
        raise ValueError("ORBITS processor is not allowlisted")
    if not isinstance(data, bytes) or not data:
        raise ValueError("ORBITS requires non-empty immutable bytes")
    image = os.environ.get("ORACLE_ARC_ORBITS_WORKER_IMAGE", "oracle-arc-orbits-worker:local").strip()
    if not image or any(ch.isspace() for ch in image):
        raise RuntimeError("Invalid ORBITS worker image configuration")
    command = [
        "podman", "run", "--rm", "--interactive", "--pull=never",
        "--network=none", "--ipc=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit=32",
        "--memory=512m", "--memory-swap=512m", "--cpus=1",
        "--user=65534:65534",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--ulimit=nofile=64:64", image,
    ]
    request = {
        "processor_id": processor_id,
        "data_base64": base64.b64encode(data).decode("ascii"),
    }
    try:
        completed = subprocess.run(
            command, input=json.dumps(request), text=True,
            capture_output=True, timeout=60, check=False,
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": os.environ.get("HOME", ""),
                "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", ""),
            },
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("ORBITS processor exceeded its 60-second deadline") from exc
    if completed.returncode != 0:
        raise RuntimeError("Isolated ORBITS processor failed")
    try:
        result = json.loads(completed.stdout)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Isolated ORBITS processor returned invalid JSON") from exc
    if not isinstance(result, dict) or not isinstance(result.get("result"), dict):
        raise RuntimeError("Isolated ORBITS processor returned an invalid result contract")
    return result["result"]
