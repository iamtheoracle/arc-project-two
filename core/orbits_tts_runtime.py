"""Fail-closed local-only TTS container runner."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import wave
import re
import subprocess
from pathlib import Path
from typing import Any


def run_local_tts(text: str, voice_id: str = "local-default") -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ValueError("TTS text is empty or exceeds the 4,000 character limit")
    if voice_id != "local-default":
        raise ValueError("Requested TTS voice is not in the reviewed local voice catalogue")
    model_dir = os.environ.get("ORACLE_ARC_TTS_MODEL_DIR", "").strip()
    image = os.environ.get("ORACLE_ARC_TTS_WORKER_IMAGE", "oracle-arc-tts-worker:local").strip()
    model_path = Path(model_dir).expanduser()
    required = ("voice.onnx", "voice.onnx.json", "oracle-arc-tts-manifest.json")
    if (not model_dir or not model_path.is_absolute() or not model_path.is_dir()
            or "," in str(model_path) or not all((model_path / name).is_file() for name in required)):
        raise RuntimeError("A complete separately installed local TTS model directory is required")
    model_dir = str(model_path.resolve())
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@+-]{0,254}", image):
        raise RuntimeError("Invalid TTS worker image configuration")
    command = [
        "podman", "run", "--rm", "--interactive", "--pull=never",
        "--network=none", "--ipc=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit=32",
        "--memory=1g", "--memory-swap=1g", "--cpus=2", "--user=65534:65534",
        "--mount", f"type=bind,src={model_dir},dst=/models/active,ro=true",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--ulimit=nofile=64:64", image,
    ]
    request = {"processor_id": "audio.synthesize", "text": text, "voice_id": voice_id}
    try:
        completed = subprocess.run(
            command, input=json.dumps(request), text=True, capture_output=True,
            timeout=120, check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                 "HOME": "/nonexistent", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("Local TTS exceeded its 120-second deadline") from exc
    if completed.returncode != 0:
        raise RuntimeError("Isolated local TTS worker failed")
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Local TTS worker returned invalid JSON") from exc
    result = payload.get("result") if isinstance(payload, dict) else None
    if (not isinstance(result, dict) or result.get("synthesis_status") != "completed"
            or result.get("inference_location") != "local"
            or result.get("format") != "audio/wav"
            or not isinstance(result.get("audio_base64"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", str(result.get("sha256", "")))):
        raise RuntimeError("Local TTS worker returned an invalid result contract")
    try:
        audio = base64.b64decode(result["audio_base64"], validate=True)
        if not audio or len(audio) > 20 * 1024 * 1024:
            raise ValueError("audio size")
        if hashlib.sha256(audio).hexdigest() != result["sha256"]:
            raise ValueError("audio digest")
        with wave.open(io.BytesIO(audio), "rb") as wav_file:
            channels, width, rate, frames = (wav_file.getnchannels(), wav_file.getsampwidth(),
                                             wav_file.getframerate(), wav_file.getnframes())
            duration = frames / rate if rate else 0
            if (channels not in (1, 2) or width not in (2, 4) or not 8000 <= rate <= 48000
                    or frames <= 0 or duration > 300
                    or result.get("sample_rate_hz") != rate
                    or result.get("channels") != channels
                    or result.get("size_bytes") != len(audio)):
                raise ValueError("audio metadata")
    except (ValueError, TypeError, wave.Error) as exc:
        raise RuntimeError("Local TTS worker returned invalid or unverifiable WAV audio") from exc
    return result
