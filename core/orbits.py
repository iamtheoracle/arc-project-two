"""ORBITS controlled media intake and trusted-processor dispatch.

This layer validates uploaded bytes and metadata. It does not execute file contents,
load processors from manifests, or claim OCR/ASR/vision inference where no trusted
isolated processor has been installed.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable


class OrbitAssetRejected(ValueError):
    pass


class OrbitProcessorUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class OrbitAsset:
    asset_id: str
    media_type: str
    mime_type: str
    filename: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class Processor:
    processor_id: str
    media_type: str
    max_input_bytes: int
    handler: Callable[[OrbitAsset, bytes], dict[str, Any]]
    isolated: bool


_LIMITS = {
    "image": 15 * 1024 * 1024,
    "audio": 25 * 1024 * 1024,
    "document": 20 * 1024 * 1024,
}
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image", "image/png"),
    (b"\xff\xd8\xff", "image", "image/jpeg"),
    (b"RIFF", "image", "image/webp"),
    (b"GIF87a", "image", "image/gif"),
    (b"GIF89a", "image", "image/gif"),
    (b"%PDF-", "document", "application/pdf"),
    (b"ID3", "audio", "audio/mpeg"),
    (b"OggS", "audio", "audio/ogg"),
    (b"RIFF", "audio", "audio/wav"),
)


def _detect(data: bytes) -> tuple[str, str]:
    if data.startswith(b"RIFF") and len(data) >= 12:
        kind = data[8:12]
        if kind == b"WEBP":
            return "image", "image/webp"
        if kind == b"WAVE":
            return "audio", "audio/wav"
    for signature, media_type, mime in _SIGNATURES:
        if data.startswith(signature):
            if mime == "image/webp":
                continue
            if mime == "audio/wav":
                continue
            return media_type, mime
    if data:
        sample = data[:4096]
        lowered = sample.lstrip().lower()
        if (lowered.startswith((b"<svg", b"<html", b"<!doctype", b"<script", b"<?xml"))
                or any(byte < 9 or 13 < byte < 32 for byte in sample)):
            raise OrbitAssetRejected("Active markup and binary archive formats are not accepted as plain text")
        try:
            sample.decode("utf-8")
            return "document", "text/plain"
        except UnicodeDecodeError:
            pass
    raise OrbitAssetRejected("Unsupported or unrecognized media format")


def validate_asset(data: bytes, filename: str, declared_mime: str | None = None) -> OrbitAsset:
    if not isinstance(data, bytes) or not data:
        raise OrbitAssetRejected("Upload must contain non-empty bytes")
    if not isinstance(filename, str) or not 1 <= len(filename) <= 180:
        raise OrbitAssetRejected("Filename is invalid")
    if filename in {".", ".."} or "/" in filename or "\\" in filename or "\x00" in filename:
        raise OrbitAssetRejected("Filename must be a basename without path components")
    if re.search(r"[\x00-\x1f]", filename):
        raise OrbitAssetRejected("Filename contains control characters")
    media_type, mime_type = _detect(data)
    if len(data) > _LIMITS[media_type]:
        raise OrbitAssetRejected("Upload exceeds the media-type size limit")
    if declared_mime and declared_mime != mime_type:
        raise OrbitAssetRejected("Declared MIME type does not match detected content")
    return OrbitAsset(
        asset_id="orb_" + uuid.uuid4().hex,
        media_type=media_type,
        mime_type=mime_type,
        filename=filename,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


class OrbitProcessorRegistry:
    """Registry for code-installed processors; developer manifests cannot add handlers."""

    def __init__(self):
        self._processors: dict[str, Processor] = {}

    def register(self, processor_id: str, media_type: str, max_input_bytes: int,
                 handler: Callable[[OrbitAsset, bytes], dict[str, Any]],
                 *, isolated: bool = False) -> None:
        if not isinstance(processor_id, str) or not re.fullmatch(r"[a-z][a-z0-9._-]{1,63}", processor_id):
            raise ValueError("Processor identifier is invalid")
        if media_type not in _LIMITS or not isinstance(max_input_bytes, int) or not 1 <= max_input_bytes <= _LIMITS[media_type]:
            raise ValueError("Processor media type or input budget is invalid")
        if not callable(handler) or isolated is not True:
            raise PermissionError("Only platform-installed isolated processors may be registered")
        if processor_id in self._processors:
            raise ValueError("Processor identifier is already registered")
        self._processors[processor_id] = Processor(
            processor_id, media_type, max_input_bytes, handler, True
        )

    def process(self, processor_id: str, asset: OrbitAsset, data: bytes) -> dict[str, Any]:
        processor = self._processors.get(processor_id)
        if processor is None:
            raise OrbitProcessorUnavailable("No trusted processor is installed for this operation")
        if not isinstance(asset, OrbitAsset) or not isinstance(data, bytes):
            raise OrbitAssetRejected("ORBITS requires a validated asset and immutable byte content")
        verified = validate_asset(data, asset.filename, asset.mime_type)
        if (verified.media_type != asset.media_type or verified.sha256 != asset.sha256
                or len(data) != asset.size_bytes):
            raise OrbitAssetRejected("Asset bytes or detected type changed after validation")
        if asset.media_type != processor.media_type:
            raise OrbitAssetRejected("Asset media type does not match the installed processor")
        if len(data) > processor.max_input_bytes:
            raise OrbitAssetRejected("Asset exceeds the installed processor's input budget")
        result = processor.handler(asset, data)
        if not isinstance(result, dict):
            raise RuntimeError("ORBITS processor returned an invalid result")
        try:
            encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("ORBITS processor output is not JSON serializable") from exc
        if len(encoded.encode("utf-8")) > 1_000_000:
            raise RuntimeError("ORBITS processor output exceeds one megabyte")
        return result
