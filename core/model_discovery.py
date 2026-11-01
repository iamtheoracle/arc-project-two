"""Bounded, local-only Ollama discovery and provider readiness checks.

Discovery is descriptive, never authorization: a discovered model cannot be used
until an application has an enabled model route to it. Unknown capabilities stay false.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx


class DiscoveryError(RuntimeError):
    """The local model service could not provide a trustworthy inventory."""


@dataclass(frozen=True)
class DiscoveredCapabilities:
    text: bool = False
    vision: bool = False
    tool_calling: bool = False
    embeddings: bool = False
    streaming: bool = False
    structured_output: bool = False


@dataclass(frozen=True)
class DiscoveredModel:
    model_id: str
    digest: str | None
    size_bytes: int | None
    capabilities: DiscoveredCapabilities
    capability_source: str


@dataclass(frozen=True)
class ProviderHealth:
    provider_id: str
    healthy: bool
    status: str
    version: str | None = None


class LocalOllamaDiscovery:
    """Talk only to loopback Ollama; all calls have explicit time and size bounds."""

    def __init__(self, host: str = "http://127.0.0.1:11434",
                 timeout_seconds: float = 3.0, client: httpx.Client | None = None):
        parsed = urlsplit(host)
        if (parsed.scheme not in {"http", "https"} or parsed.hostname not in
                {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise ValueError("Model discovery is restricted to a loopback Ollama endpoint")
        if not 0.1 <= timeout_seconds <= 15:
            raise ValueError("Discovery timeout must be between 0.1 and 15 seconds")
        self.base_url = host.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.client = client or httpx.Client(timeout=timeout_seconds)

    def _json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self.client.request(
                method, self.base_url + path, json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise DiscoveryError("Model service returned an invalid response")
            return data
        except DiscoveryError:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            # Do not expose endpoint details, headers, or provider response bodies.
            raise DiscoveryError("Local model service is unavailable or returned invalid data") from exc

    def health(self) -> ProviderHealth:
        data = self._json("GET", "/api/version")
        version = data.get("version")
        if not isinstance(version, str) or not version.strip() or len(version) > 80:
            raise DiscoveryError("Local model service returned an invalid version")
        return ProviderHealth("ollama", True, "ready", version)

    def discover(self, limit: int = 100) -> list[DiscoveredModel]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 250:
            raise ValueError("Model discovery limit must be between 1 and 250")
        data = self._json("GET", "/api/tags")
        rows = data.get("models")
        if not isinstance(rows, list) or len(rows) > 1000:
            raise DiscoveryError("Local model service returned an invalid model inventory")
        discovered: list[DiscoveredModel] = []
        seen: set[str] = set()
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            name = row.get("name")
            if not isinstance(name, str) or not name.strip() or len(name) > 256 or name in seen:
                continue
            seen.add(name)
            discovered.append(self._inspect(name, row))
        return discovered

    def _inspect(self, model_id: str, row: dict[str, Any]) -> DiscoveredModel:
        data = self._json("POST", "/api/show", {"name": model_id})
        raw = data.get("capabilities")
        # Ollama reports model capabilities as a list on supported versions.
        # If absent or malformed, do not infer capabilities from a model name/tag.
        values = set(x for x in raw if isinstance(x, str)) if isinstance(raw, list) else set()
        details = data.get("details") if isinstance(data.get("details"), dict) else {}
        size = row.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            size = None
        digest = row.get("digest")
        if not isinstance(digest, str) or len(digest) > 128:
            digest = None
        caps = DiscoveredCapabilities(
            text="completion" in values,
            vision="vision" in values,
            tool_calling="tools" in values,
            embeddings="embedding" in values,
            # Streaming and constrained JSON are API/runtime properties and are
            # deliberately not inferred from a model's tags.
            streaming=False,
            structured_output=False,
        )
        source = "ollama_api_show" if isinstance(raw, list) else "unknown"
        return DiscoveredModel(model_id, digest, size, caps, source)

    def public_inventory(self, limit: int = 100) -> list[dict[str, Any]]:
        return [
            {"model_id": item.model_id, "digest": item.digest,
             "size_bytes": item.size_bytes, "capabilities": asdict(item.capabilities),
             "capability_source": item.capability_source}
            for item in self.discover(limit)
        ]
