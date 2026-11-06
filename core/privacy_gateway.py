"""Privacy-aware provider routing. Remote inference is public-data-only.

The caller supplies a trusted policy created by server-side application authorization;
request JSON must never construct or widen this policy.
"""
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
    allowed_providers: tuple[str, ...]
    data_classification: str = "private"
    allow_remote: bool = False
    allowed_regions: tuple[str, ...] = ("local",)
    policy_version: int = 1


class PrivacyAwareModelGateway:
    REMOTE_PROVIDER_IDS = frozenset({"openrouter", "groq", "gemini", "claude"})

    def __init__(
        self,
        local_gateway: ModelGateway | None = None,
        remote_providers: dict[str, Any] | None = None,
    ):
        # This path is local by construction; remote selection requires a trusted policy.
        self.local_gateway = local_gateway if local_gateway is not None else ModelGateway(provider_id="ollama")
        if remote_providers is not None:
            self.remote_providers = dict(remote_providers)
        else:
            configs = {item.provider_id: item for item in PROVIDERS}
            self.remote_providers = {
                name: OpenAICompatibleProvider(config) for name, config in configs.items()
            }
            self.remote_providers["claude"] = AnthropicMessagesProvider()

    def chat(
        self,
        policy: InferencePolicy,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        temperature: float = 0.7,
        provider_id: str = "ollama",
    ) -> Any:
        if not isinstance(policy.tenant_id, str) or not policy.tenant_id.strip():
            raise PermissionError("Trusted tenant identity is required")
        if not isinstance(policy.application_id, str) or not policy.application_id.strip():
            raise PermissionError("Trusted application identity is required")
        if policy.data_classification not in {"public", "internal", "private", "sensitive", "restricted"}:
            raise PermissionError("Unknown data classification; inference is denied")
        validate_inference_request(model, messages, tools, stream, temperature)
        if not isinstance(provider_id, str) or provider_id not in policy.allowed_providers:
            raise PermissionError("Provider is not allowlisted by application policy")
        if provider_id == "ollama":
            if "local" not in policy.allowed_regions:
                raise PermissionError("Local inference is not permitted by policy")
            return self.local_gateway.chat(
                model, messages, tools=tools, stream=stream, temperature=temperature
            )
        if provider_id not in self.REMOTE_PROVIDER_IDS or provider_id not in self.remote_providers:
            raise PermissionError("Unknown remote provider")
        if not policy.allow_remote or policy.data_classification != "public":
            raise PermissionError("Remote inference is permitted only for explicitly authorized public data")
        if tools or stream:
            raise PermissionError("Remote adapter does not support tools or streaming in this contract")
        # Remote endpoint currently has no verified region attestation; only an explicit
        # "unspecified" region allowance can authorize it until residency metadata exists.
        if "unspecified" not in policy.allowed_regions:
            raise PermissionError("Remote provider region is not verified against policy")
        adapter = self.remote_providers[provider_id]
        chat_response = getattr(adapter, "chat_response", None)
        if not callable(chat_response):
            raise PermissionError("Remote provider adapter does not implement the normalized response contract")
        response = chat_response({"messages": messages}, model=model, temperature=temperature)
        message = response.get("message") if isinstance(response, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Remote provider returned no text response")
        return {
            "message": {"content": content},
            "provider": provider_id,
            "remote": True,
            "usage": {
                "prompt_tokens": int(response.get("prompt_eval_count", 0) or 0),
                "completion_tokens": int(response.get("eval_count", 0) or 0),
            },
        }

