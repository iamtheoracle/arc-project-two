"""Trusted integration manifest inspection and least-privilege selection.

Manifests are data only. This module never downloads, imports, installs or executes
extension code. Trust is established with an HMAC signature from a configured publisher.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-+][0-9A-Za-z.-]+)?$")
KINDS = {"plugin", "extension", "connector"}
RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
APP_VERSION = "0.1.1"


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class InspectedManifest:
    integration_id: str
    kind: str
    version: str
    publisher: str
    description: str
    capabilities: tuple[str, ...]
    permissions: tuple[str, ...]
    min_app_version: str
    max_app_version: str | None
    risk: str
    artifact_sha256: str
    signature: str
    health_url: str | None = None

    def signed_payload(self) -> dict[str, Any]:
        return {
            "integration_id": self.integration_id, "kind": self.kind,
            "version": self.version, "publisher": self.publisher,
            "description": self.description, "capabilities": list(self.capabilities),
            "permissions": list(self.permissions), "min_app_version": self.min_app_version,
            "max_app_version": self.max_app_version, "risk": self.risk,
            "artifact_sha256": self.artifact_sha256, "health_url": self.health_url,
        }


def _version_tuple(value: str) -> tuple[int, int, int]:
    if not VERSION_RE.fullmatch(value):
        raise ManifestError("Invalid semantic version")
    return tuple(int(part) for part in re.split(r"[.+-]", value)[:3])


def canonical_manifest_payload(raw: dict[str, Any]) -> bytes:
    fields = (
        "integration_id", "kind", "version", "publisher", "description",
        "capabilities", "permissions", "min_app_version", "max_app_version",
        "risk", "artifact_sha256", "health_url",
    )
    payload = {key: raw.get(key) for key in fields}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign_manifest(raw: dict[str, Any], publisher_key: str) -> str:
    """Helper for build/release tooling; the publisher key must never be sent by API clients."""
    return hmac.new(publisher_key.encode(), canonical_manifest_payload(raw), hashlib.sha256).hexdigest()


def inspect_manifest(raw: dict[str, Any], trusted_publishers: dict[str, str],
                     app_version: str = APP_VERSION,
                     allowed_permissions: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ManifestError("Manifest must be an object")
    required = {"integration_id", "kind", "version", "publisher", "description",
                "capabilities", "permissions", "min_app_version", "risk",
                "artifact_sha256", "signature"}
    if not required.issubset(raw):
        raise ManifestError("Manifest is missing required fields")
    integration_id, kind, publisher = raw["integration_id"], raw["kind"], raw["publisher"]
    if not isinstance(integration_id, str) or not ID_RE.fullmatch(integration_id):
        raise ManifestError("Invalid integration ID")
    if not isinstance(kind, str) or kind not in KINDS:
        raise ManifestError("Unsupported integration kind")
    if not isinstance(publisher, str) or publisher not in trusted_publishers:
        raise ManifestError("Publisher is not trusted")
    for key in ("version", "min_app_version"):
        if not isinstance(raw[key], str) or not VERSION_RE.fullmatch(raw[key]):
            raise ManifestError("Invalid version constraint")
    maximum = raw.get("max_app_version")
    if maximum is not None and (not isinstance(maximum, str) or not VERSION_RE.fullmatch(maximum)):
        raise ManifestError("Invalid maximum app version")
    if maximum and _version_tuple(maximum) < _version_tuple(raw["min_app_version"]):
        raise ManifestError("Inverted app version range")
    description = raw["description"]
    if not isinstance(description, str) or not description.strip() or len(description) > 500:
        raise ManifestError("Invalid description")
    for key in ("capabilities", "permissions"):
        values = raw[key]
        if not isinstance(values, list) or len(values) > 40 or any(
            not isinstance(v, str) or not ID_RE.fullmatch(v) for v in values
        ) or len(set(values)) != len(values):
            raise ManifestError("Invalid capability or permission list")
    risk = raw["risk"]
    if not isinstance(risk, str) or risk not in RISK_ORDER:
        raise ManifestError("Invalid risk classification")
    digest = raw["artifact_sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ManifestError("Invalid artifact digest")
    health_url = raw.get("health_url")
    if health_url is not None and (
        not isinstance(health_url, str) or not health_url.startswith("https://") or len(health_url) > 500
    ):
        raise ManifestError("Health checks must use an HTTPS URL")
    signature = raw["signature"]
    expected = sign_manifest(raw, trusted_publishers[publisher])
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise ManifestError("Manifest signature is invalid")
    app = _version_tuple(app_version)
    compatible = app >= _version_tuple(raw["min_app_version"]) and (
        maximum is None or app <= _version_tuple(maximum)
    )
    permissions = set(raw["permissions"])
    if allowed_permissions is not None and not permissions.issubset(allowed_permissions):
        permission_status = "denied"
    else:
        permission_status = "within_policy"
    return {
        "integration_id": integration_id, "kind": kind, "version": raw["version"],
        "publisher": publisher, "description": description,
        "capabilities": list(raw["capabilities"]), "permissions": sorted(permissions),
        "risk": risk, "artifact_sha256": digest, "signature_valid": True,
        "compatible": compatible, "permission_status": permission_status,
        "eligible_for_review": compatible and permission_status == "within_policy",
        "health_status": "unknown", "health_url_configured": bool(health_url),
        "installed": False, "active": False,
    }


def load_trust_keys() -> dict[str, str]:
    try:
        value = json.loads(os.environ.get("ORACLE_ARC_MANIFEST_TRUST_KEYS", "{}"))
    except json.JSONDecodeError as exc:
        raise ManifestError("Manifest trust configuration is invalid") from exc
    if not isinstance(value, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) or len(v) < 32
        for k, v in value.items()
    ):
        raise ManifestError("Manifest trust keys must be publisher-to-secret mappings")
    return value


def load_manifest_directory(directory: str | Path, trusted_publishers: dict[str, str],
                            allowed_permissions: set[str] | None = None) -> list[dict[str, Any]]:
    root = Path(directory).resolve()
    if not root.exists():
        return []
    if not root.is_dir():
        raise ManifestError("Manifest path is not a directory")
    results = []
    for path in sorted(root.glob("*.json")):
        if path.is_symlink() or path.resolve().parent != root:
            continue
        if path.stat().st_size > 64_000:
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            results.append(inspect_manifest(raw, trusted_publishers,
                                            allowed_permissions=allowed_permissions))
        except (OSError, json.JSONDecodeError, ManifestError):
            results.append({"manifest_file": path.name, "eligible_for_review": False,
                            "inspection_error": "invalid_or_untrusted_manifest"})
    return results


def select_safest(candidates: list[dict[str, Any]], required_capabilities: set[str],
                  allowed_permissions: set[str]) -> dict[str, Any] | None:
    eligible = []
    for item in candidates:
        if not item.get("eligible_for_review") or not item.get("signature_valid"):
            continue
        # Unknown health is not a pass. A trusted health adapter must report healthy.
        if item.get("health_status") != "healthy":
            continue
        if not required_capabilities.issubset(set(item.get("capabilities", []))):
            continue
        if not set(item.get("permissions", [])).issubset(allowed_permissions):
            continue
        if not item.get("compatible"):
            continue
        eligible.append(item)
    if not eligible:
        return None
    eligible.sort(key=lambda item: (
        RISK_ORDER.get(item.get("risk"), 99),
        len(item.get("permissions", [])),
        0 if item.get("health_status") == "healthy" else 1,
        item["integration_id"],
    ))
    return eligible[0]
