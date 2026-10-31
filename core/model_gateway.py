"""Provider-neutral, policy-aware model gateway for Oracle Arc.

Only the local Ollama adapter is enabled in this first milestone. Remote providers
must be added as explicit adapters with their own privacy, billing and contract tests.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
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
        provider_id = provider.manifest.provider_id
        if not provider_id or provider_id.strip() != provider_id:
            raise ValueError("Provider ID must be a non-empty normalized string.")
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
        host = os.environ.get("OLLAMA_HOST")
        self._client = ollama.Client(host=host, timeout=timeout) if host else ollama.Client(timeout=timeout)
        self.manifest = ProviderManifest(
            provider_id="ollama",
            display_name="Ollama (local)",
            execution_location="local",
            capabilities=ModelCapabilities(tool_calling=True, streaming=True),
            description="Local model inference through the owner's configured Ollama host.",
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
        return self.provider.chat(model, messages, tools=tools, stream=stream, temperature=temperature)

    def provider_manifest(self) -> Dict[str, Any]:
        return self.provider.manifest.public_dict()
