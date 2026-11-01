"""Offline faster-whisper worker. Model files must already exist at /models/active."""
from __future__ import annotations

import base64
import io
import json
import hashlib
import re
import os
import sys


def execute(payload: dict) -> dict:
    if not isinstance(payload, dict) or set(payload) != {"processor_id", "data_base64"}:
        raise ValueError("Invalid ASR request")
    if payload["processor_id"] != "audio.transcribe":
        raise ValueError("ASR processor is not allowlisted")
    encoded = payload["data_base64"]
    if not isinstance(encoded, str) or len(encoded) > 34_000_000:
        raise ValueError("Audio exceeds the encoded input budget")
    data = base64.b64decode(encoded, validate=True)
    if not data or len(data) > 25 * 1024 * 1024:
        raise ValueError("Audio is empty or exceeds the 25 MB limit")
    model_path = "/models/active"
    required = ("config.json", "model.bin")
    manifest_path = os.path.join(model_path, "oracle-arc-model-manifest.json")
    if not all(os.path.isfile(os.path.join(model_path, name)) for name in required) or not os.path.isfile(manifest_path):
        raise RuntimeError("Installed local ASR model or integrity manifest is incomplete")
    with open(manifest_path, "r", encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    if (not isinstance(manifest, dict) or not isinstance(manifest.get("repo_id"), str)
            or not re.fullmatch(r"[0-9a-fA-F]{40}", str(manifest.get("revision", "")))
            or not isinstance(manifest.get("sha256"), dict)):
        raise RuntimeError("Installed local ASR model manifest is invalid")
    for name in required:
        expected = manifest["sha256"].get(name)
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise RuntimeError("Installed local ASR model checksum is missing")
        digest = hashlib.sha256()
        with open(os.path.join(model_path, name), "rb") as model_file:
            for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise RuntimeError("Installed local ASR model checksum mismatch")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from faster_whisper import WhisperModel
    model = WhisperModel(model_path, device="cpu", compute_type="int8",
                         cpu_threads=2, num_workers=1, local_files_only=True)
    segments, info = model.transcribe(
        io.BytesIO(data), beam_size=3, vad_filter=True,
        condition_on_previous_text=False, word_timestamps=False,
    )
    text_parts = []
    for segment in segments:
        text_parts.append(segment.text)
        if sum(map(len, text_parts)) > 100_000:
            raise ValueError("ASR transcript exceeds 100 KB")
    return {
        "media_type": "audio", "format": "local-faster-whisper",
        "language": info.language, "language_probability": round(float(info.language_probability), 4),
        "duration_seconds": round(float(info.duration), 3),
        "text": "".join(text_parts).strip(),
        "transcription_status": "completed",
        "inference_location": "local",
    }


if __name__ == "__main__":
    try:
        request = json.load(sys.stdin)
        result = execute(request)
        encoded = json.dumps({"result": result}, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 1_000_000:
            raise ValueError("ASR output exceeds one megabyte")
        print(encoded)
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__}))
        raise SystemExit(1)
