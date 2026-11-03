"""Provider-neutral, policy-aware model gateway for Oracle Arc.

Only the local Ollama adapter is enabled in this first milestone. Remote providers
must be added as explicit adapters with their own privacy, billing and contract tests.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlsplit
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

import ollama

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
    """Local Ollama adapter. It never downloads models or sends data to a cloud API."""
    def __init__(self) -> None:
        timeout = float(os.environ.get("ORACLE_ARC_OLLAMA_TIMEOUT_SECONDS", "120"))
        if timeout <= 0 or timeout > 900:
            raise ValueError("ORACLE_ARC_OLLAMA_TIMEOUT_SECONDS must be between 0 and 900.")
        host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip()
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
        self._client = ollama.Client(host=host, timeout=timeout)
        self.manifest = ProviderManifest(
            provider_id="ollama",
            display_name="Ollama (local)" if is_local else "Ollama (remote)",
            execution_location="local" if is_local else "remote",
            capabilities=ModelCapabilities(tool_calling=True, streaming=True),
            description="Ollama inference through the configured endpoint; execution location is disclosed in this manifest.",
        )

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

class ModelGateway:
    """Routes model requests through an explicitly registered provider."""
    def __init__(self, registry: Optional[ProviderRegistry] = None, provider_id: Optional[str] = None) -> None:
        self.registry = registry or ProviderRegistry()
        if registry is None:
            self.registry.register(OllamaProvider())
        self.provider_id = provider_id or os.environ.get("ORACLE_ARC_PROVIDER", "ollama")
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
        capabilities = self.provider.manifest.capabilities
        if tools and not capabilities.tool_calling:
            raise ValueError("The selected provider does not support tool calling.")
        if stream and not capabilities.streaming:
            raise ValueError("The selected provider does not support streaming.")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("A non-empty model identifier is required.")
        if not isinstance(messages, list) or not messages:
            raise ValueError("At least one chat message is required.")
        for message in messages:
            if (not isinstance(message, dict)
                    or message.get("role") not in {"system", "user", "assistant", "tool"}
                    or not isinstance(message.get("content"), str)):
                raise ValueError("Chat messages must contain a supported role and string content.")
        if not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
            raise ValueError("Temperature must be between 0 and 2.")
        return self.provider.chat(model, messages, tools=tools, stream=stream, temperature=temperature)

    def provider_manifest(self) -> Dict[str, Any]:
        return self.provider.manifest.public_dict()
