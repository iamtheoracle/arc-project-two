"""Safe staging for owner-approved integration artifacts.

Artifacts are copied as inert bytes only. This module never extracts archives,
imports modules, starts processes, or grants runtime permissions.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

TOKEN = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
VERSION = re.compile(r"^[0-9]+\\.[0-9]+\\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
MAX_ARTIFACT_BYTES = 25 * 1024 * 1024


class ArtifactError(ValueError):
    pass


def stage_approved_artifact(
    integration_id: str,
    version: str,
    expected_sha256: str,
    staging_dir: str | Path,
    install_dir: str | Path,
) -> dict[str, str | int]:
    """Verify a pre-positioned artifact and atomically store it without executing it."""
    if not isinstance(integration_id, str) or not TOKEN.fullmatch(integration_id):
        raise ArtifactError("Invalid integration identifier")
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ArtifactError("Invalid integration version")
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise ArtifactError("Invalid expected artifact digest")

    source_root = Path(staging_dir).resolve()
    target_root = Path(install_dir).resolve()
    if not source_root.is_dir():
        raise ArtifactError("Artifact staging directory is unavailable")
    if target_root == source_root or source_root in target_root.parents:
        raise ArtifactError("Install directory must be separate from staging")
    source = source_root / f"{integration_id}-{version}.artifact"
    if source.is_symlink() or not source.is_file() or source.resolve().parent != source_root:
        raise ArtifactError("Staged artifact is missing or unsafe")
    size = source.stat().st_size
    if size <= 0 or size > MAX_ARTIFACT_BYTES:
        raise ArtifactError("Artifact size is outside the allowed range")

    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected_sha256:
        raise ArtifactError("Artifact digest does not match the approved manifest")

    target_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target_root.is_symlink():
        raise ArtifactError("Install directory cannot be a symlink")
    destination = target_root / f"{integration_id}-{version}.artifact"
    if destination.exists() or destination.is_symlink():
        raise ArtifactError("This exact artifact version is already staged")

    fd, temporary_name = tempfile.mkstemp(prefix=".oracle-arc-", dir=target_root)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, destination)
        os.chmod(destination, 0o600)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    return {"artifact_path": str(destination), "sha256": actual, "size_bytes": size,
            "status": "staged_inert"}
