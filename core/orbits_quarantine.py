"""Quarantined document intake with fail-closed malware scanning and retention.

Only scanner-clean files can proceed to extraction/indexing. Quarantine metadata and
tombstones are retained for audit; file bytes are removed when retention expires.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from core.orbits import OrbitAsset


class MalwareScannerUnavailable(RuntimeError):
    pass


class MalwareDetected(RuntimeError):
    pass


class QuarantineError(RuntimeError):
    pass


def clamav_scan(path: Path, timeout_seconds: int = 60) -> str:
    """Return a scanner signature on clean input; fail closed on all scanner errors."""
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 1 <= timeout_seconds <= 120:
        raise ValueError("ClamAV timeout must be between 1 and 120 seconds")
    executable = os.environ.get("ORACLE_ARC_CLAMSCAN", "clamscan").strip()
    if not executable or "\x00" in executable:
        raise MalwareScannerUnavailable("ClamAV executable is not configured safely")
    try:
        result = subprocess.run(
            [executable, "--no-summary", "--stdout", str(path)],
            text=True, capture_output=True, timeout=timeout_seconds, check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                 "HOME": "/nonexistent"},
        )
    except FileNotFoundError as exc:
        raise MalwareScannerUnavailable("ClamAV scanner is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise MalwareScannerUnavailable("ClamAV scan exceeded its deadline") from exc
    output = (result.stdout + "\n" + result.stderr).strip()
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    # Match ClamAV's complete per-file status suffix, not arbitrary occurrences
    # of words such as "OK" or "FOUND" in filenames or diagnostic messages.
    if result.returncode == 0 and any(line.endswith(": OK") for line in lines):
        return "\n".join(lines[-3:])[-500:]
    if result.returncode == 1 and any(line.endswith(" FOUND") for line in lines):
        raise MalwareDetected("Malware detected; file remains quarantined")
    raise MalwareScannerUnavailable("ClamAV returned an indeterminate scan result")


class DocumentQuarantineStore:
    def __init__(self, database_path: str, quarantine_dir: str | None = None,
                 scanner=clamav_scan):
        self.database_path = str(database_path)
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = Path(quarantine_dir or os.environ.get(
            "ORACLE_ARC_QUARANTINE_DIR", "data/quarantine"
        )).expanduser()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = self.root.resolve()
        try:
            self.root.chmod(0o700)
        except OSError as exc:
            raise QuarantineError("Could not secure the quarantine storage directory") from exc
        self.scanner = scanner
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS arc_document_quarantine(
                    asset_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    application_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    stored_name TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                      ('quarantined','clean','infected','scanner_error','expired','deleted')),
                    scanner_result TEXT,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    deleted_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS arc_quarantine_expiry
                  ON arc_document_quarantine(status,expires_at);
                CREATE TABLE IF NOT EXISTS arc_document_quarantine_audit(
                    event_id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    application_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    occurred_at INTEGER NOT NULL
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(arc_document_quarantine)")}
            if "document_id" not in columns:
                db.execute("ALTER TABLE arc_document_quarantine ADD COLUMN document_id TEXT")
        try:
            Path(self.database_path).chmod(0o600)
        except OSError as exc:
            raise QuarantineError("Could not secure quarantine metadata database permissions") from exc

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.database_path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _path(self, stored_name: str) -> Path:
        if not re.fullmatch(r"orb_[a-f0-9]{32}\.bin", stored_name):
            raise QuarantineError("Invalid quarantine object key")
        path = (self.root / stored_name).resolve()
        if path.parent != self.root:
            raise QuarantineError("Quarantine object escaped its storage root")
        return path

    def _audit(self, db, row, action: str, now: int) -> None:
        db.execute(
            "INSERT INTO arc_document_quarantine_audit VALUES(?,?,?,?,?,?,?,?)",
            ("qaud_" + uuid.uuid4().hex, row["asset_id"], row["tenant_id"],
             row["application_id"], row["principal_id"], action, row["sha256"], now),
        )

    def expire_due(self, now: int | None = None) -> int:
        """Delete expired bytes while retaining metadata and a durable tombstone."""
        current = int(time.time()) if now is None else int(now)
        removed = 0
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM arc_document_quarantine WHERE expires_at<=? "
                "AND status IN ('quarantined','clean','infected','scanner_error')",
                (current,),
            ).fetchall()
            for row in rows:
                path = self._path(row["stored_name"])
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    raise QuarantineError("Could not enforce quarantine retention") from exc
                if row["document_id"]:
                    document = db.execute(
                        """SELECT content_sha256 FROM arc_documents WHERE document_id=?
                           AND tenant_id=? AND application_id=? AND principal_id=? AND status='active'""",
                        (row["document_id"], row["tenant_id"], row["application_id"],
                         row["principal_id"]),
                    ).fetchone()
                    if document is not None:
                        db.execute(
                            "UPDATE arc_documents SET status='deleted',content='',updated_at=? WHERE document_id=? AND status='active'",
                            (current, row["document_id"]),
                        )
                        db.execute(
                            "INSERT INTO arc_document_access_audit VALUES(?,?,?,?,?,?,?,?)",
                            ("daud_" + uuid.uuid4().hex, row["tenant_id"], row["application_id"],
                             row["principal_id"], "quarantine_retention_expired",
                             document["content_sha256"], 0, current),
                        )
                db.execute(
                    "UPDATE arc_document_quarantine SET status='expired',deleted_at=? "
                    "WHERE asset_id=?",
                    (current, row["asset_id"]),
                )
                self._audit(db, row, "retention_expired_and_bytes_deleted", current)
                removed += 1
        return removed

    def _reauthorize(self, identity):
        # Recheck current credential state and grants immediately before file access.
        from core.document_retrieval import DocumentRetrievalStore
        documents = DocumentRetrievalStore(self.database_path)
        current = documents._reauthorize(identity)
        # Quarantine is required for every ORBITS processor, not only document
        # indexing. Indexing permissions are checked separately by the indexing
        # endpoint/store so image and audio processing do not need that grant.
        documents.security.require(current, "orbits.process")
        return current

    def ingest(self, identity, asset: OrbitAsset, data: bytes,
               retention_seconds: int = 604800) -> dict:
        identity = self._reauthorize(identity)
        if not 60 <= retention_seconds <= 31536000:
            raise ValueError("Retention must be between 60 seconds and 365 days")
        if not isinstance(asset, OrbitAsset) or not isinstance(data, bytes):
            raise ValueError("A validated ORBITS asset and immutable bytes are required")
        digest = hashlib.sha256(data).hexdigest()
        if digest != asset.sha256 or len(data) != asset.size_bytes:
            raise ValueError("Quarantined bytes do not match the validated asset")
        self.expire_due()
        now = int(time.time())
        stored_name = asset.asset_id + ".bin"
        path = self._path(stored_name)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        scope = (identity.tenant_id, identity.application_id, identity.principal_id)
        try:
            with self._db() as db:
                db.execute(
                    """INSERT INTO arc_document_quarantine
                    (asset_id,tenant_id,application_id,principal_id,filename,sha256,
                     size_bytes,stored_name,status,scanner_result,created_at,expires_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (asset.asset_id, *scope, asset.filename, digest, len(data), stored_name,
                     "quarantined", None, now, now + retention_seconds),
                )
                row = db.execute(
                    "SELECT * FROM arc_document_quarantine WHERE asset_id=?",
                    (asset.asset_id,),
                ).fetchone()
                self._audit(db, row, "quarantined", now)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        try:
            scanner_result = self.scanner(path)
        except MalwareDetected:
            with self._db() as db:
                row = db.execute("SELECT * FROM arc_document_quarantine WHERE asset_id=?",
                                 (asset.asset_id,)).fetchone()
                db.execute("UPDATE arc_document_quarantine SET status='infected' WHERE asset_id=?",
                           (asset.asset_id,))
                self._audit(db, row, "malware_detected", int(time.time()))
            raise
        except Exception as exc:
            with self._db() as db:
                row = db.execute("SELECT * FROM arc_document_quarantine WHERE asset_id=?",
                                 (asset.asset_id,)).fetchone()
                db.execute("UPDATE arc_document_quarantine SET status='scanner_error' WHERE asset_id=?",
                           (asset.asset_id,))
                self._audit(db, row, "scanner_failed_closed", int(time.time()))
            if isinstance(exc, MalwareScannerUnavailable):
                raise
            raise MalwareScannerUnavailable("Malware scanner failed; file remains quarantined") from exc
        with self._db() as db:
            row = db.execute("SELECT * FROM arc_document_quarantine WHERE asset_id=?",
                             (asset.asset_id,)).fetchone()
            db.execute(
                "UPDATE arc_document_quarantine SET status='clean',scanner_result=? WHERE asset_id=?",
                (str(scanner_result)[:500], asset.asset_id),
            )
            self._audit(db, row, "scanner_clean", int(time.time()))
        return {"asset_id": asset.asset_id, "sha256": digest, "status": "clean",
                "expires_at": now + retention_seconds}

    def link_document(self, identity, asset_id: str, document_id: str) -> bool:
        from core.document_retrieval import DocumentRetrievalStore
        documents = DocumentRetrievalStore(self.database_path)
        current = documents._reauthorize(identity)
        documents.security.require(current, "document.index")
        if not isinstance(asset_id, str) or not re.fullmatch(r"orb_[a-f0-9]{32}", asset_id):
            raise ValueError("Invalid quarantine asset identifier")
        if not isinstance(document_id, str) or not re.fullmatch(r"doc_[a-f0-9]{32}", document_id):
            raise ValueError("Invalid indexed document identifier")
        with self._db() as db:
            asset = db.execute(
                """SELECT status,document_id FROM arc_document_quarantine
                   WHERE asset_id=? AND tenant_id=? AND application_id=? AND principal_id=?""",
                (asset_id, current.tenant_id, current.application_id, current.principal_id),
            ).fetchone()
            document = db.execute(
                """SELECT 1 FROM arc_documents WHERE document_id=? AND tenant_id=?
                   AND application_id=? AND principal_id=? AND status='active'""",
                (document_id, current.tenant_id, current.application_id, current.principal_id),
            ).fetchone()
            if asset is None or asset["status"] != "clean" or document is None:
                raise QuarantineError("Only clean, principal-scoped quarantine assets can link to active indexed documents")
            if asset["document_id"] not in (None, document_id):
                raise QuarantineError("Quarantine asset is already linked to another indexed document")
            db.execute(
                "UPDATE arc_document_quarantine SET document_id=? WHERE asset_id=?",
                (document_id, asset_id),
            )
        return True

    def delete(self, identity, asset_id: str) -> bool:
        from core.document_retrieval import DocumentRetrievalStore
        documents = DocumentRetrievalStore(self.database_path)
        identity = documents._reauthorize(identity)
        documents.security.require(identity, "document.delete")
        if not isinstance(asset_id, str) or not re.fullmatch(r"orb_[a-f0-9]{32}", asset_id):
            raise ValueError("Invalid quarantine asset identifier")
        with self._db() as db:
            row = db.execute(
                """SELECT * FROM arc_document_quarantine WHERE asset_id=? AND tenant_id=?
                AND application_id=? AND principal_id=? AND status IN
                ('quarantined','clean','infected','scanner_error')""",
                (asset_id, identity.tenant_id, identity.application_id, identity.principal_id),
            ).fetchone()
            if row is None:
                return False
            now = int(time.time())
            if row["document_id"]:
                document = db.execute(
                    """SELECT content_sha256 FROM arc_documents WHERE document_id=?
                       AND tenant_id=? AND application_id=? AND principal_id=? AND status='active'""",
                    (row["document_id"], identity.tenant_id, identity.application_id,
                     identity.principal_id),
                ).fetchone()
                if document is not None:
                    db.execute(
                        "UPDATE arc_documents SET status='deleted',content='',updated_at=? WHERE document_id=? AND status='active'",
                        (now, row["document_id"]),
                    )
                    db.execute(
                        "INSERT INTO arc_document_access_audit VALUES(?,?,?,?,?,?,?,?)",
                        ("daud_" + uuid.uuid4().hex, identity.tenant_id, identity.application_id,
                         identity.principal_id, "quarantine_asset_deleted",
                         document["content_sha256"], 0, now),
                    )
            self._path(row["stored_name"]).unlink(missing_ok=True)
            db.execute("UPDATE arc_document_quarantine SET status='deleted',deleted_at=? WHERE asset_id=?",
                       (now, asset_id))
            self._audit(db, row, "owner_requested_bytes_deleted", now)
            return True

    def audit(self, identity, asset_id: str) -> list[dict]:
        from core.document_retrieval import DocumentRetrievalStore
        documents = DocumentRetrievalStore(self.database_path)
        identity = documents._reauthorize(identity)
        if "document.audit" not in identity.capabilities and "document.delete" not in identity.capabilities:
            from core.tenant_security import AuthorizationError
            raise AuthorizationError("Document audit capability is not granted")
        with self._db() as db:
            rows = db.execute(
                """SELECT action,sha256,occurred_at FROM arc_document_quarantine_audit
                WHERE asset_id=? AND tenant_id=? AND application_id=? AND principal_id=?
                ORDER BY rowid""",
                (asset_id, identity.tenant_id, identity.application_id, identity.principal_id),
            ).fetchall()
        return [dict(row) for row in rows]
