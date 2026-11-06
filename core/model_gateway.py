"""Provider-neutral, policy-aware model gateway for Oracle Arc.

Only explicitly registered providers are reachable; request validation is shared with
the privacy-aware gateway so direct and tenant-scoped calls enforce the same contract.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import math
from urllib.parse import urlsplit
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

import ollama
from .inference_contract import validate_inference_request
from .providers import (
    PROVIDERS as REMOTE_PROVIDER_CONFIGS,
    AnthropicMessagesProvider,
    OpenAICompatibleProvider,
    ProviderConfig,
)


@dataclass(frozen=True)
class ModelCapabilities:
    text: bool = True
    vision: bool = False
    audio_input: bool = False
    audio_output: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    streaming: bool = False


@dataclass(frozen=True)
class ProviderManifest:
    provider_id: str
    display_name: str
    execution_location: str
    capabilities: ModelCapabilities
    enabled: bool = True
    description: str = ""

    def public_dict(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "execution_location": self.execution_location,
            "capabilities": {
                "text": self.capabilities.text,
                "vision": self.capabilities.vision,
                "audio_input": self.capabilities.audio_input,
                "audio_output": self.capabilities.audio_output,
                "tool_calling": self.capabilities.tool_calling,
                "structured_output": self.capabilities.structured_output,
                "streaming": self.capabilities.streaming,
            },
            "enabled": self.enabled,
            "description": self.description,
        }


@runtime_checkable
class ModelProvider(Protocol):
    manifest: ProviderManifest

    def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        temperature: float = 0.7,
    ) -> Any: ...


class ProviderRegistry:
    """In-memory registry; registration is explicit and duplicate-safe."""

    def __init__(self) -> None:
        self._providers: Dict[str, ModelProvider] = {}

    def register(self, provider: ModelProvider) -> None:
        manifest = getattr(provider, "manifest", None)
        if not isinstance(manifest, ProviderManifest):
            raise ValueError("Provider must expose a valid ProviderManifest.")
        provider_id = manifest.provider_id
        if not isinstance(provider_id, str) or not provider_id or provider_id.strip() != provider_id:
            raise ValueError("Provider ID must be a non-empty normalized string.")
        if not provider_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Provider ID contains unsupported characters.")
        if manifest.execution_location not in {"local", "remote", "test"}:
            raise ValueError("Provider execution location must be local, remote, or test.")
        if not isinstance(manifest.capabilities, ModelCapabilities):
            raise ValueError("Provider capabilities must use ModelCapabilities.")
        if not callable(getattr(provider, "chat", None)):
            raise ValueError("Provider must implement a callable chat method.")
        if provider_id in self._providers:
            raise ValueError(f"Provider '{provider_id}' is already registered.")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> ModelProvider:
        provider = self._providers.get(provider_id)
        if provider is None or not provider.manifest.enabled:
            raise ValueError(f"Model provider '{provider_id}' is not enabled.")
        return provider

    def manifests(self) -> List[Dict[str, Any]]:
        return [provider.manifest.public_dict() for provider in self._providers.values()]


class OllamaProvider:
    """Configured Ollama adapter with explicit host routing and remote-host safeguards."""

    def __init__(self, host: Optional[str] = None, timeout_seconds: Optional[float] = None) -> None:
        timeout = float(timeout_seconds if timeout_seconds is not None else os.environ.get("ORACLE_ARC_OLLAMA_TIMEOUT_SECONDS", "120"))
        if not math.isfinite(timeout) or timeout <= 0 or timeout > 900:
            raise ValueError("ORACLE_ARC_OLLAMA_TIMEOUT_SECONDS must be between 0 and 900.")
        host = (host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).strip()
        parsed = urlsplit(host)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("OLLAMA_HOST must be a valid HTTP(S) URL without embedded credentials.")
        hostname = parsed.hostname.lower()
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        is_local = hostname in local_hosts
        if not is_local and os.environ.get("ORACLE_ARC_ALLOW_REMOTE_OLLAMA", "false").lower() != "true":
            raise ValueError("Remote Ollama is disabled. Set ORACLE_ARC_ALLOW_REMOTE_OLLAMA=true only after reviewing the data destination and transport security.")
        if not is_local and parsed.scheme != "https":
            raise ValueError("Remote Ollama connections must use HTTPS.")
        self._host = host
        self._client = ollama.Client(host=host, timeout=timeout)
        self.manifest = ProviderManifest(
            provider_id="ollama",
            display_name="Ollama (local)" if is_local else "Ollama (remote)",
            execution_location="local" if is_local else "remote",
            capabilities=ModelCapabilities(tool_calling=True, streaming=True),
            description="Ollama inference through the configured endpoint; execution location is disclosed in this manifest.",
        )

    def set_timeout_seconds(self, timeout_seconds: float) -> None:
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 900):
            raise ValueError("Provider timeout must be greater than 0 and at most 900 seconds.")
        old_client = self._client
        self._client = ollama.Client(host=self._host, timeout=float(timeout_seconds))
        close = getattr(old_client, "close", None)
        if callable(close):
            close()

    def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        temperature: float = 0.7,
    ) -> Any:
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "options": {"temperature": temperature},
        }
        if tools:
            kwargs["tools"] = tools
        return self._client.chat(**kwargs, stream=True) if stream else self._client.chat(**kwargs)


class OpenAICompatibleModelAdapter:
    """Fixed-endpoint remote adapter with the same validated tool-call contract as Ollama."""

    def __init__(self, config: ProviderConfig, timeout_seconds: float = 30.0) -> None:
        self.config = config
        self.client = OpenAICompatibleProvider(config, timeout_seconds=timeout_seconds)
        self.manifest = ProviderManifest(
            provider_id=config.provider_id,
            display_name=config.provider_id.replace("-", " ").title(),
            execution_location="remote",
            capabilities=ModelCapabilities(tool_calling=True, streaming=False),
            enabled=self.client.configured,
            description="Fixed HTTPS provider endpoint; API credentials are read server-side.",
        )

    def set_timeout_seconds(self, timeout_seconds: float) -> None:
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 900):
            raise ValueError("Provider timeout must be greater than 0 and at most 900 seconds.")
        self.client.timeout_seconds = float(timeout_seconds)

    def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        temperature: float = 0.7,
    ) -> Any:
        if stream:
            raise ValueError("Streaming is not enabled for this remote provider adapter.")
        return self.client.chat_response(
            {"messages": messages}, tools=tools, temperature=temperature, model=model
        )


class AnthropicModelAdapter:
    """Native Claude Messages API adapter normalized to the platform tool contract."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.client = AnthropicMessagesProvider(timeout_seconds=timeout_seconds)
        self.manifest = ProviderManifest(
            provider_id="claude",
            display_name="Anthropic Claude",
            execution_location="remote",
            capabilities=ModelCapabilities(tool_calling=True, streaming=False),
            enabled=self.client.configured,
            description="Anthropic Messages API; credentials remain server-side and remote egress is policy-gated.",
        )

    def set_timeout_seconds(self, timeout_seconds: float) -> None:
        self.client.set_timeout_seconds(timeout_seconds)

    def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        temperature: float = 0.7,
    ) -> Any:
        if stream:
            raise ValueError("Streaming is not enabled for Claude in this adapter.")
        return self.client.chat_response(
            {"messages": messages}, tools=tools, temperature=temperature, model=model
        )


class ModelGateway:
    """Routes validated model requests through an explicitly registered provider."""

    def __init__(self, registry: Optional[ProviderRegistry] = None, provider_id: Optional[str] = None, host: Optional[str] = None, timeout_seconds: Optional[float] = None) -> None:
        self._owns_registry = registry is None
        self.provider_id = provider_id or "ollama"
        if timeout_seconds is not None and (
            isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 900
        ):
            raise ValueError("Provider timeout must be greater than 0 and at most 900 seconds.")
        self.registry = registry or ProviderRegistry()
        if registry is None:
            if self.provider_id == "ollama":
                self.registry.register(OllamaProvider(host=host, timeout_seconds=timeout_seconds))
            elif self.provider_id == "claude":
                self.registry.register(AnthropicModelAdapter(timeout_seconds=timeout_seconds or 30.0))
            else:
                config = next((item for item in REMOTE_PROVIDER_CONFIGS
                               if item.provider_id == self.provider_id), None)
                if config is not None:
                    self.registry.register(OpenAICompatibleModelAdapter(config, timeout_seconds=timeout_seconds or 30.0))
        # Fail closed: no silent fallback from a requested remote provider to local or vice versa.
        self.provider = self.registry.get(self.provider_id)

    def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        temperature: float = 0.7,
    ) -> Any:
        validate_inference_request(model, messages, tools, stream, temperature)
        capabilities = self.provider.manifest.capabilities
        if tools and not capabilities.tool_calling:
            raise ValueError("The selected provider does not support tool calling.")
        if stream and not capabilities.streaming:
            raise ValueError("The selected provider does not support streaming.")
        return self.provider.chat(model, messages, tools=tools, stream=stream, temperature=temperature)

    def set_timeout_seconds(self, timeout_seconds: float) -> None:
        """Tighten the active provider timeout as an execution deadline approaches."""
        setter = getattr(self.provider, "set_timeout_seconds", None)
        if not callable(setter):
            raise ValueError("Selected provider cannot adjust its request timeout")
        setter(timeout_seconds)

    def provider_manifest(self) -> Dict[str, Any]:
        return self.provider.manifest.public_dict()

    def close(self) -> None:
        """Release provider HTTP clients owned by this gateway instance."""
        if not self._owns_registry:
            return
        for provider in self.registry._providers.values():
            client = getattr(provider, "_client", None)
            if client is None:
                adapter = getattr(provider, "client", None)
                client = getattr(adapter, "client", adapter)
            close = getattr(client, "close", None)
            if callable(close):
                close()
