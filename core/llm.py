"""Ollama LLM interface — no API keys, fully local."""
import ollama
from typing import List, Dict, Any, Optional

class LocalLLM:
    def __init__(self, model: str = "llama3.1:8b", temperature: float = 0.7, host: Optional[str] = None):
        self.model = model
        self.temperature = temperature
        self.host = host
        self._client = ollama.Client(host=host) if host else ollama.Client()

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """Send chat completion. Supports tool calling when available."""
        kwargs = {
            "model": self.model,
            "messages": messages,
            "options": {"temperature": self.temperature},
        }
        if tools:
            kwargs["tools"] = tools

        if stream:
            return self._client.chat(**kwargs, stream=True)

        return self._client.chat(**kwargs)

    def generate(self, prompt: str, system: Optional[str] = None) -> str:
        """Simple generation."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self.chat(messages)
        return resp["message"]["content"]
