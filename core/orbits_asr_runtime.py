"""Fail-closed local-only ASR container runner.

The model is provisioned separately on the host and mounted read-only. The worker
has no network and refuses model downloads; no remote provider fallback exists.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


def run_local_asr(data: bytes) -> dict[str, Any]:
    if not isinstance(data, bytes) or not data:
        raise ValueError("ASR requires non-empty immutable audio bytes")
    model_dir = os.environ.get("ORACLE_ARC_ASR_MODEL_DIR", "").strip()
    image = os.environ.get("ORACLE_ARC_ASR_WORKER_IMAGE", "oracle-arc-asr-worker:local").strip()
    if not model_dir or not Path(model_dir).is_absolute() or not Path(model_dir).is_dir():
        raise RuntimeError("A separately installed local ASR model directory is required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@+-]{0,254}", image):
        raise RuntimeError("Invalid ASR worker image configuration")
    command = [
        "podman", "run", "--rm", "--interactive", "--pull=never",
        "--network=none", "--ipc=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit=48",
        "--memory=2g", "--memory-swap=2g", "--cpus=2",
        "--user=65534:65534",
        "--mount", f"type=bind,src={model_dir},dst=/models/active,ro=true",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=128m",
        "--ulimit=nofile=96:96", image,
    ]
    request = {"processor_id": "audio.transcribe",
               "data_base64": base64.b64encode(data).decode("ascii")}
    try:
        completed = subprocess.run(
            command, input=json.dumps(request), text=True, capture_output=True,
            timeout=300, check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                 "HOME": "/nonexistent", "HF_HUB_OFFLINE": "1",
                 "TRANSFORMERS_OFFLINE": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("Local ASR exceeded its 300-second deadline") from exc
    if completed.returncode != 0:
        raise RuntimeError("Isolated local ASR worker failed")
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Local ASR worker returned invalid JSON") from exc
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("text"), str):
        raise RuntimeError("Local ASR worker returned an invalid result contract")
    return result
