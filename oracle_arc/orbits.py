"""ORBITS: controlled intake and processing of documents and media.

Pipeline: size limit -> content sniffing (declared type must match real bytes) -> executable/archive
rejection -> malware scanners (fail closed) -> owner-bound storage with retention. Heavy processors
(audio transcription, OCR, video) are pluggable; until one is registered the asset is stored and the
processing request returns an honest "unavailable" instead of invented output.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import socket
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from .types import MediaRejected, PermissionDenied, Principal, ToolUnavailable

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

KIND_LIMITS = {"text": 2_000_000, "document": 20_000_000, "image": 10_000_000, "audio": 50_000_000,
               "video": 200_000_000}


@dataclass
class ScanResult:
    clean: bool
    engine: str
    detail: str = ""


class SignatureScanner:
    """Minimal built-in scanner: EICAR test signature only. It is NOT a substitute for a real engine."""
    name = "builtin-signature"

    def scan(self, data: bytes) -> ScanResult:
        if EICAR in data:
            return ScanResult(False, self.name, "EICAR test signature")
        return ScanResult(True, self.name)


class ClamdScanner:
    """ClamAV daemon over TCP using the INSTREAM protocol."""

    def __init__(self, host: str = "127.0.0.1", port: int = 3310, timeout: float = 10.0):
        self.name, self.host, self.port, self.timeout = "clamd", host, port, timeout

    def scan(self, data: bytes) -> ScanResult:
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as s:
            s.sendall(b"zINSTREAM\0")
            for i in range(0, len(data), 8192):
                chunk = data[i:i + 8192]
                s.sendall(struct.pack("!I", len(chunk)) + chunk)
            s.sendall(struct.pack("!I", 0))
            reply = b""
            while not reply.endswith(b"\0") and len(reply) < 4096:
                part = s.recv(1024)
                if not part:
                    break
                reply += part
        text = reply.rstrip(b"\0").decode(errors="replace").strip()
        if text.endswith("OK"):
            return ScanResult(True, self.name)
        if "FOUND" in text:
            return ScanResult(False, self.name, text)
        raise RuntimeError(f"unexpected clamd reply: {text[:80]}")


def sniff(data: bytes) -> tuple:
    """Return (kind, mime) from the real bytes, ignoring what the client claims."""
    h = data[:16]
    if h[:2] == b"MZ" or h[:4] == b"\x7fELF" or h[:4] in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
        raise MediaRejected("executable content is not accepted")
    if h[:2] == b"#!":
        raise MediaRejected("script content is not accepted")
    if h[:4] == b"PK\x03\x04" or h[:6] == b"7z\xbc\xaf\x27\x1c" or h[:3] == b"\x1f\x8b\x08":
        raise MediaRejected("archives are not accepted")
    if h[:5] == b"%PDF-":
        return "document", "application/pdf"
    if h[:8] == b"\x89PNG\r\n\x1a\n":
        return "image", "image/png"
    if h[:3] == b"\xff\xd8\xff":
        return "image", "image/jpeg"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "image", "image/gif"
    if h[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio", "audio/wav"
    if h[:3] == b"ID3" or (len(h) > 1 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0):
        return "audio", "audio/mpeg"
    if data[4:8] == b"ftyp":
        return "video", "video/mp4"
    if b"\x00" in data[:4096]:
        raise MediaRejected("unrecognised binary content")
    try:
        data[:200000].decode("utf-8")
    except UnicodeDecodeError as e:
        if e.start < len(data[:200000]) - 4:      # allow a multibyte char cut at the sample boundary
            raise MediaRejected("unrecognised binary content") from None
    return "text", "text/plain"


@dataclass
class Asset:
    id: str
    app_id: str
    user_id: str
    name: str
    kind: str
    mime: str
    size: int
    sha256: str
    status: str                  # ready | rejected
    scans: list
    created: float
    expires: float


class Orbits:
    def __init__(self, scanners=None, retention_s: float = 7 * 86400, limits: dict = None,
                 require_scanners: tuple = (), audit=None, clock=time.time):
        self.scanners = list(scanners) if scanners is not None else [SignatureScanner()]
        self.retention_s, self.limits = retention_s, {**KIND_LIMITS, **(limits or {})}
        self.require_scanners = tuple(require_scanners)
        self._assets: dict = {}
        self._blobs: dict = {}
        self._processors: dict = {}
        self._audit, self._clock = audit, clock
        self._lock = threading.Lock()

    def register_processor(self, kind: str, fn: Callable[[bytes, str], str]) -> None:
        self._processors[kind] = fn

    def ingest(self, p: Principal, name: str, data: bytes, declared_mime: str = "") -> Asset:
        def reject(msg: str):
            if self._audit:
                self._audit.append("orbits.rejected", app_id=p.app_id, user_id=p.user_id, name=name[:80], reason=msg)
            raise MediaRejected(msg)

        if not data:
            reject("empty upload")
        try:
            kind, mime = sniff(data)
        except MediaRejected as e:
            reject(str(e))
        if len(data) > self.limits[kind]:
            reject(f"{kind} exceeds the {self.limits[kind]} byte limit")
        if declared_mime and declared_mime.split(";")[0].strip() != mime and not (
                kind == "text" and declared_mime.startswith("text/") or
                kind == "text" and declared_mime in ("application/json", "application/csv")):
            reject(f"declared type {declared_mime} does not match content ({mime})")
        scans = []
        engines = set()
        for sc in self.scanners:
            try:
                r = sc.scan(data)
            except Exception as e:                      # scanner failure must never let content through
                reject(f"scanner {getattr(sc, 'name', '?')} unavailable: {type(e).__name__}")
            scans.append(r)
            engines.add(r.engine)
            if not r.clean:
                reject(f"malware detected ({r.engine}: {r.detail})")
        missing = [e for e in self.require_scanners if e not in engines]
        if missing:
            reject(f"required scanner not run: {', '.join(missing)}")
        now = self._clock()
        asset = Asset(uuid.uuid4().hex, p.app_id, p.user_id, name[:200], kind, mime, len(data),
                      hashlib.sha256(data).hexdigest(), "ready", scans, now, now + self.retention_s)
        with self._lock:
            self._assets[asset.id], self._blobs[asset.id] = asset, data
        if self._audit:
            self._audit.append("orbits.ingested", app_id=p.app_id, user_id=p.user_id, id=asset.id, kind=kind,
                               size=len(data), engines=sorted(engines))
        return asset

    def _owned(self, p: Principal, asset_id: str) -> Asset:
        a = self._assets.get(asset_id)
        if not a or a.app_id != p.app_id or a.user_id != p.user_id or a.expires < self._clock():
            raise PermissionDenied("asset not found")          # same answer for missing and not-yours
        return a

    def get(self, p: Principal, asset_id: str) -> bytes:
        self._owned(p, asset_id)
        return self._blobs[asset_id]

    def extract_text(self, p: Principal, asset_id: str, max_chars: int = 20000) -> str:
        a = self._owned(p, asset_id)
        data = self._blobs[asset_id]
        if a.kind == "text":
            text = data.decode("utf-8", errors="replace")
            if a.name.lower().endswith(".json"):
                try:
                    text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
                except ValueError:
                    pass
            elif a.name.lower().endswith(".csv"):
                rows = list(csv.reader(io.StringIO(text)))
                text = "\n".join(" | ".join(r) for r in rows[:500])
            return text[:max_chars]
        fn = self._processors.get(a.kind)
        if not fn:
            raise ToolUnavailable(f"no {a.kind} processor is connected", kind=a.kind)
        return fn(data, a.mime)[:max_chars]

    def delete(self, p: Principal, asset_id: str) -> None:
        self._owned(p, asset_id)
        with self._lock:
            self._assets.pop(asset_id, None)
            self._blobs.pop(asset_id, None)
        if self._audit:
            self._audit.append("orbits.deleted", app_id=p.app_id, user_id=p.user_id, id=asset_id)

    def sweep(self) -> int:
        now = self._clock()
        with self._lock:
            dead = [i for i, a in self._assets.items() if a.expires < now]
            for i in dead:
                self._assets.pop(i), self._blobs.pop(i)
        return len(dead)
