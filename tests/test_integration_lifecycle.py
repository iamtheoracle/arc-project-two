import hashlib

import pytest

from core.integration_lifecycle import ArtifactError, stage_approved_artifact


def test_stage_verifies_digest_and_copies_inert_artifact(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "installed"
    source.mkdir()
    payload = b"reviewed connector artifact bytes"
    digest = hashlib.sha256(payload).hexdigest()
    (source / "calendar-sync-1.2.0.artifact").write_bytes(payload)

    result = stage_approved_artifact("calendar-sync", "1.2.0", digest, source, target)

    installed = target / "calendar-sync-1.2.0.artifact"
    assert installed.read_bytes() == payload
    assert result["sha256"] == digest
    assert result["status"] == "staged_inert"
    assert installed.stat().st_mode & 0o777 == 0o600


def test_stage_rejects_digest_mismatch_and_does_not_write(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "installed"
    source.mkdir()
    (source / "calendar-sync-1.2.0.artifact").write_bytes(b"tampered")
    with pytest.raises(ArtifactError, match="digest"):
        stage_approved_artifact("calendar-sync", "1.2.0", "0" * 64, source, target)
    assert not target.exists()


def test_stage_rejects_symlink_and_invalid_identifiers(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "installed"
    source.mkdir()
    actual = source / "actual"
    actual.write_bytes(b"payload")
    (source / "calendar-sync-1.2.0.artifact").symlink_to(actual)
    digest = hashlib.sha256(b"payload").hexdigest()
    with pytest.raises(ArtifactError, match="unsafe"):
        stage_approved_artifact("calendar-sync", "1.2.0", digest, source, target)
    with pytest.raises(ArtifactError, match="identifier"):
        stage_approved_artifact("../escape", "1.2.0", digest, source, target)


def test_stage_rejects_replacement_of_existing_version(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "installed"
    source.mkdir()
    payload = b"payload"
    (source / "calendar-sync-1.2.0.artifact").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    stage_approved_artifact("calendar-sync", "1.2.0", digest, source, target)
    with pytest.raises(ArtifactError, match="already staged"):
        stage_approved_artifact("calendar-sync", "1.2.0", digest, source, target)
