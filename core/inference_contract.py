"""Shared, provider-independent validation for all model inference paths.

This contract runs before provider selection or network egress. Keep it deliberately
small and deterministic; provider-specific capability checks happen afterwards.
"""
from __future__ import annotations

from typing import Any


SUPPORTED_ROLES = frozenset({"system", "user", "assistant", "tool"})
MAX_MESSAGES = 100
MAX_MESSAGE_CHARS = 100_000
MAX_MODEL_ID_CHARS = 256


def validate_inference_request(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    stream: bool,
    temperature: float,
) -> None:
    if not isinstance(model, str) or not model.strip() or len(model) > MAX_MODEL_ID_CHARS:
        raise ValueError("Model identifier must be non-empty and at most 256 characters")
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise ValueError("Inference requires between 1 and 100 messages")
    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("role") not in SUPPORTED_ROLES
            or not isinstance(message.get("content"), str)
            or not message["content"]
            or len(message["content"]) > MAX_MESSAGE_CHARS
        ):
            raise ValueError(
                "Each message requires a supported role and non-empty text up to 100000 characters"
            )
    if (
        not isinstance(temperature, (int, float))
        or isinstance(temperature, bool)
        or not 0 <= temperature <= 2
    ):
        raise ValueError("Temperature must be between 0 and 2")
    if tools is not None and (
        not isinstance(tools, list)
        or any(not isinstance(item, dict) for item in tools)
    ):
        raise ValueError("Tools must be a list of objects")
    if not isinstance(stream, bool):
        raise ValueError("Stream must be a boolean")
