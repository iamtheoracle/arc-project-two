"""Privacy-aware provider routing. No provider is selected without explicit policy.

The caller supplies a trusted policy created by server-side application authorization;
request JSON must never construct or widen this policy.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .model_gateway import ModelGateway
from .providers import OpenAICompatibleProvider, PROVIDERS, ProviderError


@dataclass(frozen=True)
class InferencePolicy:
    tenant_id: str
    application_id: str
    allowed_providers: tuple[str, ...]
    data_classification: str = "private"
    allow_remote: bool = False
    allowed_regions: tuple[str, ...] = ("local",)
    policy_version: int = 1


def _validate_chat_request(messages: list[dict[str, Any]], temperature: float,
                          tools: list[dict[str, Any]] | None, stream: bool) -> None:
    """Apply one provider-independent request contract before any data egress."""
    if not isinstance(messages, list) or not 1 <= len(messages) <= 100:
        raise ValueError("Inference requires between 1 and 100 messages")
    for message in messages:
        if (not isinstance(message, dict)
                or message.get("role") not in {"system", "user", "assistant", "tool"}
                or not isinstance(message.get("content"), str)
                or not message["content"]
                or len(message["content"]) > 100_000):
            raise ValueError("Each message requires a supported role and non-empty text up to 100000 characters")
    if not isinstance(temperature, (int, float)) or isinstance(temperature, bool) or not 0 <= temperature <= 2:
        raise ValueError("Temperature must be between 0 and 2")
    if tools is not None and (not isinstance(tools, list) or any(not isinstance(item, dict) for item in tools)):
        raise ValueError("Tools must be a list of objects")
    if not isinstance(stream, bool):
        raise ValueError("Stream must be a boolean")


class PrivacyAwareModelGateway:
    def __init__(self, local_gateway: ModelGateway | None = None,
                 remote_providers: dict[str, OpenAICompatibleProvider] | None = None):
        self.local_gateway = local_gateway or ModelGateway()
        configs={item.provider_id:item for item in PROVIDERS}
        self.remote_providers=remote_providers or {
            name:OpenAICompatibleProvider(config) for name,config in configs.items()
        }

    def chat(self, policy: InferencePolicy, model: str, messages: list[dict[str,Any]],
             tools: list[dict[str,Any]]|None=None, stream: bool=False,
             temperature: float=0.7, provider_id: str="ollama") -> Any:
        if not policy.tenant_id or not policy.application_id:
            raise PermissionError("Trusted tenant and application identity are required")
        if policy.data_classification not in {"public", "internal", "private", "sensitive", "restricted"}:
            raise PermissionError("Unknown data classification; inference is denied")
        _validate_chat_request(messages, temperature, tools, stream)
        if not isinstance(provider_id, str) or provider_id not in policy.allowed_providers:
            raise PermissionError("Provider is not allowlisted by application policy")
        if provider_id == "ollama":
            if "local" not in policy.allowed_regions:
                raise PermissionError("Local inference is not permitted by policy")
            return self.local_gateway.chat(model,messages,tools=tools,stream=stream,temperature=temperature)
        if not policy.allow_remote or policy.data_classification in {"sensitive","restricted"}:
            raise PermissionError("Remote inference is not permitted for this data classification")
        if provider_id not in self.remote_providers or provider_id not in {"openrouter","groq","gemini"}:
            raise PermissionError("Unknown remote provider")
        if tools or stream:
            raise PermissionError("Remote adapter does not support tools or streaming in this contract")
        # Remote endpoint currently has no verified region attestation; only an explicit
        # 'unspecified' region allowance can authorize it until residency metadata exists.
        if "unspecified" not in policy.allowed_regions:
            raise PermissionError("Remote provider region is not verified against policy")
        adapter=self.remote_providers[provider_id]
        answer=adapter.chat({"messages":messages})
        return {"message":{"content":answer},"provider":provider_id,"remote":True}
