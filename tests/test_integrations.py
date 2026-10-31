import hashlib

import pytest

from core.integrations import (
    ManifestError, inspect_manifest, select_safest, sign_manifest,
)


TRUST = {"oracle-labs": "trusted-publisher-secret-that-is-long-enough-123"}
ALLOWED = {"calendar.read", "calendar.write", "storage.read"}


def manifest(**overrides):
    value = {
        "integration_id": "calendar-sync",
        "kind": "connector",
        "version": "1.2.0",
        "publisher": "oracle-labs",
        "description": "Calendar synchronization connector",
        "capabilities": ["calendar-sync"],
        "permissions": ["calendar.read"],
        "min_app_version": "0.1.0",
        "max_app_version": "1.0.0",
        "risk": "low",
        "artifact_sha256": hashlib.sha256(b"artifact").hexdigest(),
        "health_url": None,
    }
    value.update(overrides)
    value["signature"] = sign_manifest(value, TRUST["oracle-labs"])
    return value


def test_signed_manifest_is_verified_and_compatible():
    result = inspect_manifest(manifest(), TRUST, allowed_permissions=ALLOWED)
    assert result["signature_valid"] is True
    assert result["compatible"] is True
    assert result["eligible_for_review"] is True
    assert result["installed"] is False
    assert result["active"] is False
    assert len(result["manifest_digest"]) == 64


def test_untrusted_publisher_and_tampered_manifest_are_rejected():
    with pytest.raises(ManifestError, match="not trusted"):
        inspect_manifest(manifest(publisher="unknown"), TRUST)
    raw = manifest()
    raw["permissions"] = ["calendar.write"]
    with pytest.raises(ManifestError, match="signature"):
        inspect_manifest(raw, TRUST)


def test_incompatible_or_overprivileged_manifest_is_not_eligible():
    incompatible = inspect_manifest(manifest(min_app_version="9.0.0", max_app_version=None), TRUST,
                                    allowed_permissions=ALLOWED)
    assert incompatible["compatible"] is False
    assert incompatible["eligible_for_review"] is False
    overprivileged = inspect_manifest(manifest(permissions=["calendar.write"]), TRUST,
                                      allowed_permissions={"calendar.read"})
    assert overprivileged["permission_status"] == "denied"
    assert overprivileged["eligible_for_review"] is False


def test_safest_selection_prefers_lower_risk_and_fewer_permissions():
    low = inspect_manifest(manifest(), TRUST, allowed_permissions=ALLOWED)
    high_raw = manifest(integration_id="calendar-power", risk="high",
                        permissions=["calendar.read", "calendar.write"])
    high = inspect_manifest(high_raw, TRUST, allowed_permissions=ALLOWED)
    low["health_status"] = "healthy"
    high["health_status"] = "healthy"
    selected = select_safest([high, low], {"calendar-sync"}, ALLOWED)
    assert selected["integration_id"] == "calendar-sync"


def test_selection_requires_all_requested_capabilities_and_policy_permissions():
    candidate = inspect_manifest(manifest(), TRUST, allowed_permissions=ALLOWED)
    assert select_safest([candidate], {"calendar-sync", "calendar-delete"}, ALLOWED) is None
    assert select_safest([candidate], {"calendar-sync"}, {"storage.read"}) is None



def test_unknown_or_unhealthy_integrations_are_never_selected():
    candidate = inspect_manifest(manifest(), TRUST, allowed_permissions=ALLOWED)
    assert candidate["health_status"] == "unknown"
    assert select_safest([candidate], {"calendar-sync"}, ALLOWED) is None
    candidate["health_status"] = "unhealthy"
    assert select_safest([candidate], {"calendar-sync"}, ALLOWED) is None


def test_malformed_manifest_types_fail_closed():
    with pytest.raises(ManifestError):
        inspect_manifest(manifest(kind=[]), TRUST)
    with pytest.raises(ManifestError):
        inspect_manifest(manifest(risk=[]), TRUST)
