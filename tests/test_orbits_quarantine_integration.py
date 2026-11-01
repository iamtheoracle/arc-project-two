import shutil

import pytest

from core.orbits import validate_asset
from core.orbits_quarantine import DocumentQuarantineStore, MalwareDetected


pytestmark = pytest.mark.skipif(
    shutil.which("clamscan") is None,
    reason="Requires the real ClamAV scanner and signature database",
)


def test_real_clamav_accepts_clean_text_and_detects_eicar(tmp_path):
    store = DocumentQuarantineStore(
        str(tmp_path / "arc.sqlite3"), str(tmp_path / "quarantine")
    )
    identity = type("Identity", (), {
        "tenant_id": "tenant", "application_id": "app", "principal_id": "principal"
    })()
    clean = b"ordinary text for malware scanning"
    clean_asset = validate_asset(clean, "clean.txt")
    result = store.ingest(identity, clean_asset, clean)
    assert result["status"] == "clean"

    # Standard EICAR antivirus test signature; this is inert test content, not malware.
    eicar = (b"X5O!P%@AP[4\\\\PZX54(P^)7CC)7}$"
             b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*")
    eicar_asset = validate_asset(eicar, "eicar.txt")
    with pytest.raises(MalwareDetected):
        store.ingest(identity, eicar_asset, eicar)
    events = store.audit(identity, eicar_asset.asset_id)
    assert events[-1]["action"] == "malware_detected"
