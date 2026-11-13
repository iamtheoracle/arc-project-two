"""Tenant-aware inference routing with fail-closed remote egress policy."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .inference_contract import validate_inference_request
from .model_gateway import ModelGateway
from .providers import AnthropicMessagesProvider, OpenAICompatibleProvider, PROVIDERS


@dataclass(frozen=True)
class InferencePolicy:
    tenant_id: str
    application_id: str
    data_classification: str = "private"
    allow_remote: bool = False
    allowed_remote_providers: frozenset[str] = frozenset()
    allowed_regions: frozenset[str] = frozenset()
    required_region: str | None = None
    policy_version: int = 1

    def permits(self, provider_id: str, region: str | None) -> bool:
        if not self.allow_remote or self.data_classification != "public":
            return False
        if provider_id not in self.allowed_remote_providers:
            return False
        if region is None:
            if "unspecified" not in self.allowed_regions:
                return False
        elif region not in self.allowed_regions:
            return False
        if self.required_region is not None and region != self.required_region:
            return False
        return True


@dataclass(frozen=True)
class ProviderResult:
    content: Any
    provider_id: str
    remote_egress: bool
    region: str | None


class ProviderPolicyError(PermissionError):
    pass


class PrivacyAwareModelGateway:
    def __init__(
        self,
        local_gateway: ModelGateway | None = None,
        remote_providers: dict[str, tuple[Any, str | None]] | None = None,
    ):
        self.local = local_gateway if local_gateway is not None else ModelGateway(provider_id="ollama")
        self.remote: dict[str, tuple[Any, str | None]] = {}
        if remote_providers is None:
            for config in PROVIDERS:
                self.register_remote(OpenAICompatibleProvider(config), region=None)
            self.register_remote(AnthropicMessagesProvider(), region=None)
        else:
            for provider_id, (provider, region) in remote_providers.items():
                self.remote[provider_id] = (provider, region)

    def register_remote(self, provider: Any, region: str | None = None) -> None:
        provider_id = getattr(provider, "provider_id", None)
        if not provider_id:
            provider_id = getattr(getattr(provider, "config", None), "provider_id", None)
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("Remote provider must expose a stable provider_id")
        self.remote[provider_id] = (provider, region)

    def manifests(self) -> list[dict[str, Any]]:
        local = self.local.provider_manifest()
        result = [{
            "provider_id": local["provider_id"],
            "execution_location": local["execution_location"],
            "region": local.get("region"),
            "enabled": True,
        }]
        for provider_id, (provider, region) in sorted(self.remote.items()):
            result.append({
                "provider_id": provider_id,
                "execution_location": "remote",
                "region": region,
                "enabled": bool(getattr(provider, "configured", False)),
            })
        return result

    def chat(
        self,
        policy: InferencePolicy,
        model: str,
        messages: list[dict[str, Any]],
        provider_id: str = "ollama",
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        temperature: float = 0.7,
    ) -> ProviderResult:
        if not policy.tenant_id or not policy.application_id:
            raise ProviderPolicyError("Tenant and application identity are required")
        if policy.data_classification not in {"public", "internal", "private", "sensitive", "restricted"}:
            raise ProviderPolicyError("Unknown data classification")
        validate_inference_request(model, messages, tools, stream, temperature)

        if provider_id == "ollama":
            manifest = self.local.provider_manifest()
            location = manifest.get("execution_location")
            if location == "local":
                if policy.allowed_regions and "local" not in policy.allowed_regions:
                    raise ProviderPolicyError("Local inference is not permitted by policy")
            elif location == "remote":
                if not policy.permits("ollama", manifest.get("region")):
                    raise ProviderPolicyError("Remote Ollama is permitted only for explicitly authorized public data and an allowed region")
                if tools or stream:
                    raise ProviderPolicyError("Remote Ollama tool calling and streaming are not enabled by this policy")
            else:
                raise ProviderPolicyError("Ollama execution location is unknown; inference is denied")
            result = self.local.chat(model, messages, tools=tools, stream=stream, temperature=temperature)
            return ProviderResult(result, "ollama", location == "remote", manifest.get("region"))

        if provider_id not in self.remote:
            raise ProviderPolicyError("Provider is not registered for this application")
        provider, region = self.remote[provider_id]
        if not policy.permits(provider_id, region):
            raise ProviderPolicyError("Remote inference is permitted only for explicitly authorized public data and an allowed provider region")
        if tools or stream:
            raise ProviderPolicyError("Remote tool calling and streaming are not enabled by this policy")
        chat_response = getattr(provider, "chat_response", None)
        if not callable(chat_response):
            raise ProviderPolicyError("Remote provider does not implement the normalized response contract")
        response = chat_response({"messages": messages}, model=model, temperature=temperature)
        message = response.get("message") if isinstance(response, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ProviderPolicyError("Remote provider returned no text response")
        return ProviderResult(content, provider_id, True, region)

