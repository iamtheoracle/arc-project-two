"""Trusted tenant/application identity primitives (additive control-plane schema).

Bearer secrets are returned once at issuance; only salted PBKDF2 verifiers are stored.
The legacy owner API key remains separate and is not a tenant credential.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class RequestIdentity:
    credential_id: str
    tenant_id: str
    application_id: str
    principal_id: str
    capabilities: tuple[str, ...]
    policy_version: int
    issued_at: int
    expires_at: int


class TenantIdentityStore:
    def __init__(self, database_path: str):
        self.database_path = database_path
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS arc_tenants(
              tenant_id TEXT PRIMARY KEY, name TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('active','disabled')),
              created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS arc_applications(
              application_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
              name TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','disabled')),
              policy_version INTEGER NOT NULL DEFAULT 1,
              UNIQUE(tenant_id,application_id),
              FOREIGN KEY(tenant_id) REFERENCES arc_tenants(tenant_id)
            );
            CREATE TABLE IF NOT EXISTS arc_principals(
              principal_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('active','disabled')),
              FOREIGN KEY(tenant_id) REFERENCES arc_tenants(tenant_id)
            );
            CREATE TABLE IF NOT EXISTS arc_app_memberships(
              tenant_id TEXT NOT NULL, application_id TEXT NOT NULL,
              principal_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','revoked')),
              PRIMARY KEY(tenant_id,application_id,principal_id),
              FOREIGN KEY(tenant_id,application_id) REFERENCES arc_applications(tenant_id,application_id),
              FOREIGN KEY(principal_id) REFERENCES arc_principals(principal_id)
            );
            CREATE TABLE IF NOT EXISTS arc_credentials(
              credential_id TEXT PRIMARY KEY, verifier TEXT NOT NULL,
              tenant_id TEXT NOT NULL, application_id TEXT NOT NULL,
              principal_id TEXT NOT NULL, capabilities_json TEXT NOT NULL,
              expires_at INTEGER NOT NULL, revoked_at INTEGER,
              FOREIGN KEY(tenant_id,application_id) REFERENCES arc_applications(tenant_id,application_id),
              FOREIGN KEY(principal_id) REFERENCES arc_principals(principal_id)
            );
            """)
            db.commit()

    def _connect(self):
        db = sqlite3.connect(self.database_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def _verifier(secret: str, salt: bytes) -> str:
        return hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, 310_000).hex()

    def provision(self, tenant_name: str, application_name: str, principal_id: str,
                  capabilities: Iterable[str], ttl_seconds: int = 86400) -> dict:
        if not tenant_name.strip() or not application_name.strip() or not principal_id.strip():
            raise ValueError("Tenant, application and principal names are required")
        if not 60 <= ttl_seconds <= 31_536_000:
            raise ValueError("Credential lifetime must be between one minute and one year")
        caps = sorted(set(capabilities))
        if not caps or any(not isinstance(c, str) or not c.strip() or len(c) > 100 for c in caps):
            raise ValueError("At least one valid capability is required")
        tenant_id, app_id = "ten_" + uuid.uuid4().hex, "app_" + uuid.uuid4().hex
        credential_id, principal = "cred_" + uuid.uuid4().hex, principal_id
        secret, salt = secrets.token_urlsafe(48), secrets.token_bytes(16)
        verifier = salt.hex() + "$" + self._verifier(secret, salt)
        now = int(time.time())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO arc_tenants VALUES(?,?, 'active',?)", (tenant_id, tenant_name.strip(), now))
            db.execute("INSERT INTO arc_applications VALUES(?,?,?,'active',1)", (app_id, tenant_id, application_name.strip()))
            db.execute("INSERT INTO arc_principals VALUES(?,?,'active')", (principal, tenant_id))
            db.execute("INSERT INTO arc_app_memberships VALUES(?,?,?,'active')", (tenant_id, app_id, principal))
            db.execute("INSERT INTO arc_credentials VALUES(?,?,?,?,?,?,?,NULL)",
                       (credential_id, verifier, tenant_id, app_id, principal, __import__('json').dumps(caps), now + ttl_seconds))
            db.commit()
        return {"credential_id": credential_id, "secret": secret, "tenant_id": tenant_id,
                "application_id": app_id, "principal_id": principal, "expires_at": now + ttl_seconds}

    def authenticate(self, secret: str) -> RequestIdentity:
        if not isinstance(secret, str) or len(secret) < 32:
            raise PermissionError("Invalid application credential")
        # Credential IDs are intentionally not exposed in bearer tokens; bounded scan is
        # acceptable for the initial SQLite control plane and can later use keyed lookup.
        with self._connect() as db:
            rows = db.execute("""
              SELECT c.*, t.status AS tenant_status, a.status AS app_status,
                     a.policy_version, p.status AS principal_status, m.status AS membership_status
              FROM arc_credentials c
              JOIN arc_tenants t ON t.tenant_id=c.tenant_id
              JOIN arc_applications a ON a.tenant_id=c.tenant_id AND a.application_id=c.application_id
              JOIN arc_principals p ON p.principal_id=c.principal_id
              JOIN arc_app_memberships m ON m.tenant_id=c.tenant_id
                AND m.application_id=c.application_id AND m.principal_id=c.principal_id
              WHERE c.revoked_at IS NULL
            """).fetchall()
        for row in rows:
            try:
                salt_hex, expected = row["verifier"].split("$", 1)
                actual = self._verifier(secret, bytes.fromhex(salt_hex))
            except (ValueError, TypeError):
                continue
            if not hmac.compare_digest(actual, expected):
                continue
            now = int(time.time())
            if (row["expires_at"] <= now or row["tenant_status"] != "active"
                    or row["app_status"] != "active" or row["principal_status"] != "active"
                    or row["membership_status"] != "active"):
                break
            import json
            return RequestIdentity(row["credential_id"], row["tenant_id"], row["application_id"],
                row["principal_id"], tuple(json.loads(row["capabilities_json"])),
                row["policy_version"], now, row["expires_at"])
        raise PermissionError("Invalid, expired, revoked or disabled application credential")

    def provision_application(self, tenant_id: str, application_name: str,
                              principal_id: str, capabilities: Iterable[str],
                              ttl_seconds: int = 86400) -> dict:
        """Add a sibling application to an existing tenant."""
        if not application_name.strip() or not principal_id.strip():
            raise ValueError("Application and principal are required")
        if not 60 <= ttl_seconds <= 31_536_000:
            raise ValueError("Credential lifetime must be between one minute and one year")
        caps = sorted(set(capabilities))
        if not caps or any(not isinstance(c, str) or not c.strip() or len(c) > 100 for c in caps):
            raise ValueError("At least one valid capability is required")
        app_id, credential_id = "app_" + uuid.uuid4().hex, "cred_" + uuid.uuid4().hex
        secret, salt = secrets.token_urlsafe(48), secrets.token_bytes(16)
        verifier = salt.hex() + "$" + self._verifier(secret, salt)
        now = int(time.time())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            tenant = db.execute("SELECT 1 FROM arc_tenants WHERE tenant_id=? AND status='active'", (tenant_id,)).fetchone()
            principal = db.execute("SELECT 1 FROM arc_principals WHERE tenant_id=? AND principal_id=? AND status='active'", (tenant_id, principal_id)).fetchone()
            if not tenant or not principal:
                raise LookupError("Active tenant and principal membership are required")
            db.execute("INSERT INTO arc_applications VALUES(?,?,?,'active',1)", (app_id, tenant_id, application_name.strip()))
            db.execute("INSERT INTO arc_app_memberships VALUES(?,?,?,'active')", (tenant_id, app_id, principal_id))
            db.execute("INSERT INTO arc_credentials VALUES(?,?,?,?,?,?,?,NULL)",
                       (credential_id, verifier, tenant_id, app_id, principal_id, __import__('json').dumps(caps), now + ttl_seconds))
            db.commit()
        return {"credential_id": credential_id, "secret": secret, "tenant_id": tenant_id,
                "application_id": app_id, "principal_id": principal_id, "expires_at": now + ttl_seconds}

    def revoke(self, credential_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute("UPDATE arc_credentials SET revoked_at=? WHERE credential_id=? AND revoked_at IS NULL",
                                (int(time.time()), credential_id))
            db.commit()
            return cursor.rowcount == 1

    def revoke_membership(self, tenant_id: str, application_id: str, principal_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute("UPDATE arc_app_memberships SET status='revoked' WHERE tenant_id=? AND application_id=? AND principal_id=? AND status='active'",
                                (tenant_id, application_id, principal_id))
            db.commit()
            return cursor.rowcount == 1
