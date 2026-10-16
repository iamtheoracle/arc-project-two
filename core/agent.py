"""Main agent loop — sharp, multi-step reasoning with tools."""
from typing import List, Dict, Any
from .llm import LocalLLM
from .plugins import PluginRegistry

SYSTEM_PROMPT = """You are Arc, a premium local AI assistant. You are sharp, precise, and highly capable.

Rules:
- Think step by step before acting.
- Use tools when they provide better accuracy or capability than pure reasoning.
- Be concise yet complete. Prefer clarity over verbosity.
- Never invent tool results — only report what tools actually return.
- If a tool fails, explain the issue and try an alternative approach.
- Maintain context across the conversation.
- You run entirely locally with no external API dependencies.
"""

class ArcAgent:
    def __init__(self, model: str = "llama3.1:8b"):
        self.llm = LocalLLM(model=model)
        self.plugins = PluginRegistry()
        self.messages: List[Dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    def chat(self, user_input: str, max_steps: int = 8) -> str:
        self.messages.append({"role": "user", "content": user_input})

        tools = self.plugins.get_tools_schema()

        for step in range(max_steps):
            response = self.llm.chat(self.messages, tools=tools if tools else None)
            msg = response["message"]

            # Append assistant message
            self.messages.append(msg)

            # Check for tool calls
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                # Final answer
                return msg.get("content", "")

            # Execute tools
            for call in tool_calls:
                fn = call["function"]
                name = fn["name"]
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    import json
                    try:
                        args = json.loads(args)
                    except:
                        args = {}

                result = self.plugins.execute(name, args)
                self.messages.append({
                    "role": "tool",
                    "content": result,
                    "tool_call_id": call.get("id", name),
                })

        return "Reached maximum reasoning steps. Please refine your request."
