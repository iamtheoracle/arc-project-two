"""Compatibility facade for Oracle Arc's provider-neutral model gateway."""
from typing import Any, Dict, List, Optional

from .model_gateway import ModelGateway


class LocalLLM:
    """Preserves the existing agent interface while routing through ModelGateway."""
    def __init__(self, model: str = "qwen2.5:7b", temperature: float = 0.7):
        self.model = model
        self.temperature = temperature
        self.gateway = ModelGateway()

    def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict]] = None, stream: bool = False) -> Any:
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
