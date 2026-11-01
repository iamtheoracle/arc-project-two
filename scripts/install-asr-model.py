#!/usr/bin/env python3
"""Provision a pinned faster-whisper model snapshot; never used by inference workers."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from huggingface_hub import snapshot_download


def main() -> None:
    repo_id = os.environ.get("ORACLE_ARC_ASR_MODEL_ID", "").strip()
    revision = os.environ.get("ORACLE_ARC_ASR_MODEL_REVISION", "").strip()
    destination = Path(os.environ.get(
        "ORACLE_ARC_ASR_MODEL_DIR", "/opt/oracle-arc/models/whisper-small"
    )).expanduser()
    if not repo_id or not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
        raise SystemExit(
            "Set ORACLE_ARC_ASR_MODEL_ID and a 40-character immutable "
            "ORACLE_ARC_ASR_MODEL_REVISION commit hash."
        )
    destination.mkdir(parents=True, exist_ok=True, mode=0o750)
    snapshot_download(repo_id=repo_id, revision=revision, local_dir=str(destination))
    required = ("config.json", "model.bin")
    if not all((destination / name).is_file() for name in required):
        raise SystemExit("Downloaded snapshot is not a complete faster-whisper model.")
    manifest = {}
    for path in sorted(p for p in destination.rglob("*") if p.is_file()):
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        manifest[str(path.relative_to(destination))] = digest.hexdigest()
    (destination / "oracle-arc-model-manifest.json").write_text(
        json.dumps({"repo_id": repo_id, "revision": revision, "sha256": manifest},
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    # Model weights are public runtime assets; make them readable by the worker's
    # fixed non-root UID while keeping the host model directory non-writable.
    for item in destination.rglob("*"):
        if item.is_dir():
            item.chmod(0o755)
        elif item.is_file():
            item.chmod(0o644)
    destination.chmod(0o755)
    print(f"Installed pinned offline ASR model: {repo_id}@{revision}")
    print(f"Model directory: {destination}")


if __name__ == "__main__":
    main()
