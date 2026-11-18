"""Application identity and short-lived signed tokens.

Every caller is an *application* acting for a *user*. The application authenticates with its secret
and receives a token bound to (app_id, user_id). An application can only mint tokens for itself, so it
cannot impersonate another application. Note: user identity is currently vouched for by the calling
application; replace `TrustedAppAssertion` with an OIDC verifier once the identity provider is chosen.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from .types import AuthError, Principal


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@dataclass
class AppRecord:
    app_id: str
    salt: bytes
    secret_hash: bytes
    scopes: frozenset
    suspended: bool = False
    token_epoch: int = 0  # bump to invalidate every previously issued token for this app


class TrustedAppAssertion:
    """Stop-gap user verifier: the authenticated application vouches for its own user ids."""

    def verify(self, app_id: str, user_id: str) -> bool:
        return bool(user_id) and len(user_id) <= 128


class AppRegistry:
    def __init__(self, server_key: Optional[bytes] = None, user_verifier=None, store=None):
        key = server_key or (os.environ.get("ARC_SERVER_KEY", "").encode() or secrets.token_bytes(32))
        self._key = key
        self._apps: dict = {}
        self._lock = threading.Lock()
        self.user_verifier = user_verifier or TrustedAppAssertion()
        self.store = store

    @staticmethod
    def _hash(secret: str, salt: bytes) -> bytes:
        return hashlib.scrypt(secret.encode(), salt=salt, n=2 ** 12, r=8, p=1, dklen=32)

    def register_app(self, app_id: str, secret: str, scopes=()) -> None:
        if self.store is not None:
            raise RuntimeError("applications must be provisioned through the separate PostgreSQL provisioner")
        if len(secret) < 16:
            raise ValueError("application secret must be at least 16 characters")
        salt = secrets.token_bytes(16)
        with self._lock:
            self._apps[app_id] = AppRecord(app_id, salt, self._hash(secret, salt), frozenset(scopes))

    def _get_record(self, app_id: str) -> AppRecord | None:
        if self.store is not None:
            row = self.store.get_application(app_id)
            if row is None:
                return None
            return AppRecord(app_id=row["app_id"], salt=row["salt"], secret_hash=row["secret_hash"],
                             scopes=frozenset(row["scopes"]), suspended=bool(row["suspended"]),
                             token_epoch=int(row["token_epoch"]))
        return self._apps.get(app_id)

    def suspend_app(self, app_id: str) -> None:
        if self.store is not None:
            self.store.set_application_suspended(app_id, True)
            return
        self._apps[app_id].suspended = True

    def revoke_tokens(self, app_id: str) -> None:
        if self.store is not None:
            self.store.revoke_application_tokens(app_id)
            return
        self._apps[app_id].token_epoch += 1

    def authenticate_app(self, app_id: str, secret: str) -> AppRecord:
        rec = self._get_record(app_id)
        # Always compute a hash so unknown apps and wrong secrets are indistinguishable by timing.
        salt = rec.salt if rec else b"\0" * 16
        candidate = self._hash(secret or "", salt)
        if not rec or not hmac.compare_digest(candidate, rec.secret_hash) or rec.suspended:
            raise AuthError("invalid application credentials")
        return rec

    def issue_token(self, app_id: str, secret: str, user_id: str, ttl: int = 900) -> str:
        rec = self.authenticate_app(app_id, secret)
        if not self.user_verifier.verify(app_id, user_id):
            raise AuthError("user identity could not be verified")
        payload = {"a": app_id, "u": user_id, "exp": int(time.time()) + int(ttl), "e": rec.token_epoch}
        body = _b64(json.dumps(payload, separators=(",", ":")).encode())
        sig = _b64(hmac.new(self._key, body.encode(), hashlib.sha256).digest())
        return f"v1.{body}.{sig}"

    def verify_token(self, token: str) -> Principal:
        try:
            version, body, sig = token.split(".")
            if version != "v1":
                raise ValueError
            good = _b64(hmac.new(self._key, body.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(sig, good):
                raise ValueError
            payload = json.loads(_unb64(body))
        except Exception:
            raise AuthError("invalid token") from None
        rec = self._get_record(payload.get("a"))
        if not rec or rec.suspended or payload.get("e") != rec.token_epoch:
            raise AuthError("token no longer valid")
        if payload.get("exp", 0) < time.time():
            raise AuthError("token expired")
        return Principal(app_id=rec.app_id, user_id=payload["u"], scopes=rec.scopes)
