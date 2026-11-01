import pytest

from core.orbits import validate_asset
from core.orbits_quarantine import (
    DocumentQuarantineStore, MalwareDetected, MalwareScannerUnavailable,
)
from core.tenant_security import TenantSecurityStore


def identity(database_path, principal="principal-a"):
    security = TenantSecurityStore(str(database_path))
    tenant = security.create_tenant("Tenant " + principal)
    app = security.create_application(tenant, "Application")
    token = security.issue_credential(
        tenant, app, principal,
        ["orbits.process", "document.index", "document.delete", "document.audit"],
        ttl_seconds=3600,
    )
    return security.authenticate(token)


def test_quarantine_requires_clean_scan_before_reporting_success(tmp_path):
    asset = validate_asset(b"safe document text", "note.txt")
    store = DocumentQuarantineStore(
        str(tmp_path / "db.sqlite3"), str(tmp_path / "quarantine"),
        scanner=lambda path: "ClamAV clean signature",
    )
    result = store.ingest(identity(tmp_path / "db.sqlite3"), asset, b"safe document text", retention_seconds=120)
    assert result["status"] == "clean"
    assert (tmp_path / "quarantine" / (asset.asset_id + ".bin")).exists()
    actions = [x["action"] for x in store.audit(identity(), asset.asset_id)]
    assert actions == ["quarantined", "scanner_clean"]


def test_quarantine_fails_closed_and_retains_infected_or_unscannable_bytes(tmp_path):
    data = b"safe document text"
    infected = validate_asset(data, "infected.txt")
    store = DocumentQuarantineStore(
        str(tmp_path / "db.sqlite3"), str(tmp_path / "quarantine"),
        scanner=lambda path: (_ for _ in ()).throw(MalwareDetected("EICAR")),
    )
    with pytest.raises(MalwareDetected):
        store.ingest(identity(), infected, data)
    infected_path = tmp_path / "quarantine" / (infected.asset_id + ".bin")
    assert infected_path.exists()
    assert store.audit(identity(), infected.asset_id)[-1]["action"] == "malware_detected"

    unavailable = validate_asset(data, "scanner-offline.txt")
    store.scanner = lambda path: (_ for _ in ()).throw(MalwareScannerUnavailable("offline"))
    with pytest.raises(MalwareScannerUnavailable):
        store.ingest(identity(), unavailable, data)
    assert (tmp_path / "quarantine" / (unavailable.asset_id + ".bin")).exists()
    assert store.audit(identity(), unavailable.asset_id)[-1]["action"] == "scanner_failed_closed"


def test_quarantine_retention_deletes_bytes_and_keeps_audit_tombstone(tmp_path):
    data = b"retention test"
    asset = validate_asset(data, "retention.txt")
    store = DocumentQuarantineStore(
        str(tmp_path / "db.sqlite3"), str(tmp_path / "quarantine"),
        scanner=lambda path: "clean",
    )
    result = store.ingest(identity(), asset, data, retention_seconds=60)
    path = tmp_path / "quarantine" / (asset.asset_id + ".bin")
    assert path.exists()
    assert store.expire_due(now=result["expires_at"] + 1) == 1
    assert not path.exists()
    assert store.audit(identity(), asset.asset_id)[-1]["action"] == "retention_expired_and_bytes_deleted"
    assert store.expire_due(now=result["expires_at"] + 2) == 0


def test_quarantine_is_scoped_and_explicit_delete_is_audited(tmp_path):
    data = b"scoped document"
    asset = validate_asset(data, "scoped.txt")
    store = DocumentQuarantineStore(
        str(tmp_path / "db.sqlite3"), str(tmp_path / "quarantine"),
        scanner=lambda path: "clean",
    )
    store.ingest(identity(), asset, data)
    assert store.delete(identity(tmp_path / "db.sqlite3", "other-principal"), asset.asset_id) is False
    assert store.delete(identity(), asset.asset_id) is True
    assert store.audit(identity(), asset.asset_id)[-1]["action"] == "owner_requested_bytes_deleted"
