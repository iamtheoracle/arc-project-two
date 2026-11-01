#!/usr/bin/env python3
"""Provision a pinned Piper ONNX voice; inference workers never download models."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from huggingface_hub import hf_hub_download


def main() -> None:
    repo_id = os.environ.get("ORACLE_ARC_TTS_MODEL_ID", "").strip()
    revision = os.environ.get("ORACLE_ARC_TTS_MODEL_REVISION", "").strip()
    model_file = os.environ.get("ORACLE_ARC_TTS_MODEL_FILE", "").strip()
    config_file = os.environ.get("ORACLE_ARC_TTS_CONFIG_FILE", "").strip()
    license_name = os.environ.get("ORACLE_ARC_TTS_MODEL_LICENSE", "").strip()
    destination = Path(os.environ.get(
        "ORACLE_ARC_TTS_MODEL_DIR", "/opt/oracle-arc/models/piper-voice"
    )).expanduser()
    if (not repo_id or not re.fullmatch(r"[0-9a-fA-F]{40}", revision)
            or not model_file or not config_file or not license_name):
        raise SystemExit("Set model ID, immutable 40-character revision, ONNX/config filenames and verified license.")
    if any(x in model_file + config_file for x in ("..", "\\\\", "\\x00")):
        raise SystemExit("Model filenames must be safe repository-relative paths.")
    destination.mkdir(parents=True, exist_ok=True, mode=0o750)
    downloaded_model = hf_hub_download(repo_id=repo_id, filename=model_file, revision=revision)
    downloaded_config = hf_hub_download(repo_id=repo_id, filename=config_file, revision=revision)
    shutil.copyfile(downloaded_model, destination / "voice.onnx")
    shutil.copyfile(downloaded_config, destination / "voice.onnx.json")
    hashes = {}
    for name in ("voice.onnx", "voice.onnx.json"):
        digest = hashlib.sha256()
        with (destination / name).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        hashes[name] = digest.hexdigest()
    (destination / "oracle-arc-tts-manifest.json").write_text(
        json.dumps({"repo_id": repo_id, "revision": revision, "license": license_name,
                    "source_model_file": model_file, "source_config_file": config_file,
                    "sha256": hashes}, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
    for item in destination.iterdir():
        item.chmod(0o755 if item.is_dir() else 0o644)
    destination.chmod(0o755)
    print(f"Installed pinned Piper voice: {repo_id}@{revision}")
    print(f"Declared model license: {license_name} (verify it against the upstream repository before installation)")
    print(f"Model directory: {destination}")


if __name__ == "__main__":
    main()
