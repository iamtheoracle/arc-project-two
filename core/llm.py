"""Local Ollama inference adapter with explicit deadlines and bounded configuration."""
import os
from typing import Any, Dict, List, Optional
import ollama

class LocalLLM:
    def __init__(self, model: str = "qwen2.5:7b", temperature: float = 0.7):
        self.model = model
        self.temperature = temperature
        timeout = float(os.environ.get("ORACLE_ARC_OLLAMA_TIMEOUT_SECONDS", "120"))
        if timeout <= 0 or timeout > 900:
            raise ValueError("ORACLE_ARC_OLLAMA_TIMEOUT_SECONDS must be between 0 and 900.")
        host = os.environ.get("OLLAMA_HOST")
        self._client = ollama.Client(host=host, timeout=timeout) if host else ollama.Client(timeout=timeout)

    def chat(self, messages: List[Dict[str, str]], tools: Optional[List[Dict]] = None, stream: bool = False) -> Dict[str, Any]:
        kwargs = {"model": self.model, "messages": messages, "options": {"temperature": self.temperature}}
        if tools: kwargs["tools"] = tools
        if stream: return self._client.chat(**kwargs, stream=True)
        return self._client.chat(**kwargs)

    def generate(self, prompt: str, system: Optional[str] = None) -> str:
        messages = []
        if system: messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self.chat(messages)
        return response["message"]["content"]