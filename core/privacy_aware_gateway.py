"""Single privacy-aware model routing boundary for local and remote inference.

Remote execution requires an explicit request policy decision. Provider credentials and
availability never grant permission to export prompt or memory data.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
from core.model_gateway import ModelGateway
from core.providers import OpenAICompatibleProvider, ProviderConfig, PROVIDERS


class ProviderPolicyError(PermissionError):
    pass


@dataclass(frozen=True)
class InferencePolicy:
    tenant_id: str
    application_id: str
    principal_id: str
    data_classification: str = "private"
    allow_remote: bool = False
    allowed_remote_providers: frozenset[str] = frozenset()
    allowed_regions: frozenset[str] = frozenset()
    required_region: str | None = None
    policy_version: int = 1

    def permits(self, provider_id: str, region: str | None) -> bool:
        if provider_id == "ollama":
            return (
                self.allow_remote
                and "ollama" in self.allowed_remote_providers
                and self.data_classification not in {"restricted", "sensitive"}
                and (self.required_region is None or region == self.required_region)
                and (not self.allowed_regions or region in self.allowed_regions)
            )
        return (
            self.allow_remote
            and provider_id in self.allowed_remote_providers
            and self.data_classification not in {"restricted", "sensitive"}
            and (self.required_region is None or region == self.required_region)
            and (not self.allowed_regions or region in self.allowed_regions)
        )


@dataclass(frozen=True)
class ProviderResult:
    content: Any
    provider_id: str
    execution_location: str
    policy_version: int
    remote_egress: bool


class PrivacyAwareModelGateway:
    """One decision point for provider selection; never silently broadens egress."""

    def __init__(self, local_gateway: ModelGateway | None = None,
                 remote_providers: dict[str, tuple[OpenAICompatibleProvider, str | None]] | None = None):
        self.local = local_gateway or ModelGateway()
        self.remote = remote_providers or {}

    def register_remote(self, provider: OpenAICompatibleProvider, region: str | None = None):
        provider_id = provider.config.provider_id
        if provider_id in self.remote:
            raise ValueError("Remote provider already registered")
        self.remote[provider_id] = (provider, region)

    def chat(self, policy: InferencePolicy, model: str, messages: list[dict[str, Any]],
             preferred_provider: str = "ollama", tools: list[dict] | None = None,
             stream: bool = False, temperature: float = 0.7) -> ProviderResult:
        if preferred_provider == "ollama":
            manifest = self.local.provider_manifest()
            execution_location = manifest.get("execution_location", "unknown")
            remote = execution_location == "remote"
            if remote and not policy.permits("ollama", None):
                raise ProviderPolicyError("Privacy policy denies remote Ollama egress")
            result = self.local.chat(model, messages, tools=tools, stream=stream,
                                     temperature=temperature)
            return ProviderResult(result, "ollama", execution_location,
                                  policy.policy_version, remote)
        selected = self.remote.get(preferred_provider)
        if selected is None:
            raise ProviderPolicyError("Requested provider is not registered")
        provider, region = selected
        if not policy.permits(preferred_provider, region):
            raise ProviderPolicyError("Privacy policy denies remote provider egress")
        if tools or stream:
            raise ProviderPolicyError("This remote adapter does not support tool execution or streaming")
        answer = provider.chat({"messages": messages})
        return ProviderResult(answer, preferred_provider, "remote", policy.policy_version, True)

    def manifests(self) -> list[dict[str, Any]]:
        return [{
            "provider_id": "ollama",
            "execution_location": "configured-local-or-remote",
            "enabled": True,
            "remote_egress": False,
        }] + [{
            "provider_id": key, "execution_location": "remote",
            "region": region, "enabled": provider.configured,
            "remote_egress": True,
        } for key, (provider, region) in self.remote.items()]
