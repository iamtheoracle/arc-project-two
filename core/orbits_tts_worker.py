"""Offline Piper TTS worker. A pinned model and integrity manifest must be mounted at /models/active."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
import wave


def _verify_model(model_path: str) -> dict:
    model_file = os.path.join(model_path, "voice.onnx")
    config_file = os.path.join(model_path, "voice.onnx.json")
    manifest_file = os.path.join(model_path, "oracle-arc-tts-manifest.json")
    if not all(os.path.isfile(p) for p in (model_file, config_file, manifest_file)):
        raise RuntimeError("Pinned local TTS model, config or manifest is missing")
    with open(manifest_file, "r", encoding="utf-8") as stream:
        manifest = json.load(stream)
    if (not isinstance(manifest, dict)
            or not isinstance(manifest.get("repo_id"), str)
            or not re.fullmatch(r"[0-9a-fA-F]{40}", str(manifest.get("revision", "")))
            or not isinstance(manifest.get("license"), str)
            or not manifest["license"].strip()
            or not isinstance(manifest.get("sha256"), dict)):
        raise RuntimeError("Local TTS provenance manifest is invalid")
    for name, path in (("voice.onnx", model_file), ("voice.onnx.json", config_file)):
        expected = manifest["sha256"].get(name)
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise RuntimeError("Local TTS model checksum is missing")
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise RuntimeError("Local TTS model checksum mismatch")
    return manifest


def execute(payload: dict) -> dict:
    if not isinstance(payload, dict) or set(payload) != {"processor_id", "text", "voice_id"}:
        raise ValueError("Invalid TTS request")
    if payload["processor_id"] != "audio.synthesize" or payload["voice_id"] != "local-default":
        raise ValueError("TTS processor or voice is not allowlisted")
    text = payload["text"]
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ValueError("Speech text is empty or exceeds the 4,000 character limit")
    if any(ord(ch) < 32 and ch not in "\\n\\r\\t" for ch in text):
        raise ValueError("Speech text contains unsupported control characters")
    manifest = _verify_model("/models/active")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from piper import PiperVoice
    voice = PiperVoice.load("/models/active/voice.onnx", config_path="/models/active/voice.onnx.json")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)
    audio = output.getvalue()
    if not audio or len(audio) > 20 * 1024 * 1024:
        raise ValueError("Synthesized audio is empty or exceeds the 20 MB limit")
    with wave.open(io.BytesIO(audio), "rb") as wav_file:
        channels, width, rate, frames = (wav_file.getnchannels(), wav_file.getsampwidth(),
                                         wav_file.getframerate(), wav_file.getnframes())
        if channels not in (1, 2) or width not in (2, 4) or not 8000 <= rate <= 48000 or frames <= 0:
            raise ValueError("TTS worker produced unsupported or invalid PCM WAV")
        duration = frames / rate
        if duration > 300:
            raise ValueError("Synthesized audio exceeds five minutes")
    return {
        "media_type": "audio", "format": "audio/wav", "codec": "pcm",
        "channels": channels, "sample_width_bytes": width, "sample_rate_hz": rate,
        "duration_seconds": round(duration, 3), "size_bytes": len(audio),
        "sha256": hashlib.sha256(audio).hexdigest(),
        "audio_base64": base64.b64encode(audio).decode("ascii"),
        "voice_id": "local-default", "model_repo": manifest["repo_id"],
        "model_revision": manifest["revision"], "model_license": manifest["license"],
        "synthesis_status": "completed", "inference_location": "local",
    }


if __name__ == "__main__":
    try:
        request = json.load(sys.stdin)
        result = execute(request)
        encoded = json.dumps({"result": result}, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 28_000_000:
            raise ValueError("TTS response exceeds output budget")
        print(encoded)
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__}))
        raise SystemExit(1)
