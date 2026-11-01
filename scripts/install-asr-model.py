#!/usr/bin/env python3
"""Provision a pinned faster-whisper model snapshot; never used by inference workers."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download


def main() -> None:
    repo_id = os.environ.get("ORACLE_ARC_ASR_MODEL_ID", "").strip()
    revision = os.environ.get("ORACLE_ARC_ASR_MODEL_REVISION", "").strip()
    destination = Path(os.environ.get(
        "ORACLE_ARC_ASR_MODEL_DIR", "/opt/oracle-arc/models/whisper-small"
    )).expanduser()
    if not repo_id or not revision or len(revision) < 7:
        raise SystemExit(
            "Set ORACLE_ARC_ASR_MODEL_ID and an immutable "
            "ORACLE_ARC_ASR_MODEL_REVISION (commit hash)."
        )
    destination.mkdir(parents=True, exist_ok=True, mode=0o750)
    snapshot_download(repo_id=repo_id, revision=revision, local_dir=str(destination))
    required = ("config.json", "model.bin")
    if not all((destination / name).is_file() for name in required):
        raise SystemExit("Downloaded snapshot is not a complete faster-whisper model.")
    manifest = {}
    for path in sorted(p for p in destination.rglob("*") if p.is_file()):
        manifest[str(path.relative_to(destination))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (destination / "oracle-arc-model-manifest.json").write_text(
        json.dumps({"repo_id": repo_id, "revision": revision, "sha256": manifest},
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Installed pinned offline ASR model: {repo_id}@{revision}")
    print(f"Model directory: {destination}")


if __name__ == "__main__":
    main()
