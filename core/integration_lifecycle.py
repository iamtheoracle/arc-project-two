"""Safe staging for owner-approved integration artifacts.

Artifacts are copied as inert bytes only. This module never extracts archives,
imports modules, starts processes, or grants runtime permissions.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path

TOKEN = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
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

    source_input, target_input = Path(staging_dir), Path(install_dir)
    if source_input.is_symlink() or target_input.is_symlink():
        raise ArtifactError("Artifact directories cannot be symlinks")
    source_root, target_root = source_input.resolve(), target_input.resolve()
    if not source_root.is_dir():
        raise ArtifactError("Artifact staging directory is unavailable")
    if target_root == source_root or source_root in target_root.parents:
        raise ArtifactError("Install directory must be separate from staging")

    source = source_root / f"{integration_id}-{version}.artifact"
    if source.is_symlink() or not source.is_file() or source.resolve().parent != source_root:
        raise ArtifactError("Staged artifact is missing or unsafe")

    source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    temporary_name = None
    fd = None
    try:
        metadata = os.fstat(source_fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0 or metadata.st_size > MAX_ARTIFACT_BYTES:
            raise ArtifactError("Artifact size or file type is outside the allowed range")

        # Verify before creating the install directory or writing any installed bytes.
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(os.dup(source_fd), "rb") as input_file:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                size += len(chunk)
                if size > MAX_ARTIFACT_BYTES:
                    raise ArtifactError("Artifact exceeds the maximum allowed size")
                digest.update(chunk)
        if size == 0 or digest.hexdigest() != expected_sha256:
            raise ArtifactError("Artifact digest does not match the approved manifest")

        target_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target_root.is_symlink():
            raise ArtifactError("Install directory cannot be a symlink")
        destination = target_root / f"{integration_id}-{version}.artifact"
        if destination.exists() or destination.is_symlink():
            raise ArtifactError("This exact artifact version is already staged")

        fd, temporary_name = tempfile.mkstemp(prefix=".oracle-arc-", dir=target_root)
        os.fchmod(fd, 0o600)
        os.lseek(source_fd, 0, os.SEEK_SET)
        copied_digest = hashlib.sha256()
        copied_size = 0
        with os.fdopen(fd, "wb") as output, os.fdopen(os.dup(source_fd), "rb") as input_file:
            fd = None
            for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                copied_size += len(chunk)
                if copied_size > MAX_ARTIFACT_BYTES:
                    raise ArtifactError("Artifact exceeds the maximum allowed size")
                copied_digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        actual = copied_digest.hexdigest()
        if copied_size != size or actual != expected_sha256:
            raise ArtifactError("Artifact changed during staging")
        # link() is atomic and fails rather than replacing an existing installed version.
        os.link(temporary_name, destination, follow_symlinks=False)
        os.unlink(temporary_name)
        temporary_name = None
    finally:
        os.close(source_fd)
        if fd is not None:
            os.close(fd)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass

    return {"artifact_path": str(destination), "sha256": actual, "size_bytes": copied_size,
            "status": "staged_inert"}


def verify_staged_artifact(
    integration_id: str,
    version: str,
    expected_sha256: str,
    install_dir: str | Path,
) -> bool:
    """Verify an inert staged artifact without importing or executing it."""
    if not isinstance(integration_id, str) or not TOKEN.fullmatch(integration_id):
        raise ArtifactError("Invalid integration identifier")
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ArtifactError("Invalid integration version")
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise ArtifactError("Invalid expected artifact digest")
    root_input = Path(install_dir)
    if root_input.is_symlink():
        raise ArtifactError("Install directory cannot be a symlink")
    root = root_input.resolve()
    path = root / f"{integration_id}-{version}.artifact"
    if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
        return False
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0 or metadata.st_size > MAX_ARTIFACT_BYTES:
            return False
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(os.dup(fd), "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                if size > MAX_ARTIFACT_BYTES:
                    return False
                digest.update(chunk)
        return size == metadata.st_size and digest.hexdigest() == expected_sha256
    finally:
        os.close(fd)
