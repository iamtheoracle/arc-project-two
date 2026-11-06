"""Compatibility facade routing every local model call through ModelGateway."""
from typing import Any, Dict, List, Optional

from .model_gateway import ModelGateway


class LocalLLM:
    """Keep the ArcAgent interface while centralizing provider policy and validation."""
    def __init__(
        self,
        model: str = "qwen2.5:7b",
        temperature: float = 0.7,
        host: Optional[str] = None,
    ):
        self.model = model
        self.temperature = temperature
        # This compatibility facade is intentionally local-only. Remote providers must
        # be selected through PrivacyAwareModelGateway or the policy-checked platform worker.
        self.gateway = ModelGateway(provider_id="ollama", host=host)
        manifest = self.gateway.provider_manifest()
        if manifest.get("execution_location") != "local":
            self.gateway.close()
            raise PermissionError("LocalLLM refuses remote Ollama; use a policy-checked public-data route instead.")

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
    ) -> Any:
        return self.gateway.chat(
            model=self.model,
            messages=messages,
            tools=tools,
            stream=stream,
            temperature=self.temperature,
        )

    def generate(self, prompt: str, system: Optional[str] = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self.chat(messages)
        return response["message"]["content"]
