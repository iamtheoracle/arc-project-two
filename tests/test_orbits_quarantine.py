import pytest

from core.orbits import validate_asset
from core.orbits_quarantine import (
    DocumentQuarantineStore, MalwareDetected, MalwareScannerUnavailable,
)
from core.tenant_security import TenantSecurityStore


def provision_identity(database_path, principal="principal-a"):
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
    who = provision_identity(tmp_path / "db.sqlite3")
    result = store.ingest(who, asset, b"safe document text", retention_seconds=120)
    assert result["status"] == "clean"
    assert (tmp_path / "quarantine" / (asset.asset_id + ".bin")).exists()
    actions = [x["action"] for x in store.audit(who, asset.asset_id)]
    assert actions == ["quarantined", "scanner_clean"]


def test_quarantine_fails_closed_and_retains_infected_or_unscannable_bytes(tmp_path):
    data = b"safe document text"
    infected = validate_asset(data, "infected.txt")
    store = DocumentQuarantineStore(
        str(tmp_path / "db.sqlite3"), str(tmp_path / "quarantine"),
        scanner=lambda path: (_ for _ in ()).throw(MalwareDetected("EICAR")),
    )
    who = provision_identity(tmp_path / "db.sqlite3")
    with pytest.raises(MalwareDetected):
        store.ingest(who, infected, data)
    infected_path = tmp_path / "quarantine" / (infected.asset_id + ".bin")
    assert infected_path.exists()
    assert store.audit(who, infected.asset_id)[-1]["action"] == "malware_detected"

    unavailable = validate_asset(data, "scanner-offline.txt")
    store.scanner = lambda path: (_ for _ in ()).throw(MalwareScannerUnavailable("offline"))
    with pytest.raises(MalwareScannerUnavailable):
        store.ingest(who, unavailable, data)
    assert (tmp_path / "quarantine" / (unavailable.asset_id + ".bin")).exists()
    assert store.audit(who, unavailable.asset_id)[-1]["action"] == "scanner_failed_closed"


def test_quarantine_retention_deletes_bytes_and_keeps_audit_tombstone(tmp_path):
    data = b"retention test"
    asset = validate_asset(data, "retention.txt")
    store = DocumentQuarantineStore(
        str(tmp_path / "db.sqlite3"), str(tmp_path / "quarantine"),
        scanner=lambda path: "clean",
    )
    who = provision_identity(tmp_path / "db.sqlite3")
    result = store.ingest(who, asset, data, retention_seconds=60)
    path = tmp_path / "quarantine" / (asset.asset_id + ".bin")
    assert path.exists()
    assert store.expire_due(now=result["expires_at"] + 1) == 1
    assert not path.exists()
    assert store.audit(who, asset.asset_id)[-1]["action"] == "retention_expired_and_bytes_deleted"
    assert store.expire_due(now=result["expires_at"] + 2) == 0


def test_quarantine_is_scoped_and_explicit_delete_is_audited(tmp_path):
    data = b"scoped document"
    asset = validate_asset(data, "scoped.txt")
    store = DocumentQuarantineStore(
        str(tmp_path / "db.sqlite3"), str(tmp_path / "quarantine"),
        scanner=lambda path: "clean",
    )
    who = provision_identity(tmp_path / "db.sqlite3")
    other = provision_identity(tmp_path / "db.sqlite3", "other-principal")
    store.ingest(who, asset, data)
    assert store.delete(other, asset.asset_id) is False
    assert store.delete(who, asset.asset_id) is True
    assert store.audit(who, asset.asset_id)[-1]["action"] == "owner_requested_bytes_deleted"


def test_quarantine_rechecks_credential_revocation_before_storing_bytes(tmp_path):
    from core.tenant_security import AuthorizationError

    data = b"revocation race test"
    asset = validate_asset(data, "revoked.txt")
    database = tmp_path / "db.sqlite3"
    who = provision_identity(database)
    store = DocumentQuarantineStore(
        str(database), str(tmp_path / "quarantine"), scanner=lambda path: "clean"
    )
    TenantSecurityStore(str(database)).revoke_credential(who.credential_id)
    with pytest.raises(AuthorizationError):
        store.ingest(who, asset, data)
    assert not (tmp_path / "quarantine" / (asset.asset_id + ".bin")).exists()
