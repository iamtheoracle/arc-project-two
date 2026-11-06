"""Shared types and errors for Oracle Arc."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional


class Risk(IntEnum):
    """How consequential a tool action is. Ordering matters: higher = riskier."""
    READ = 0
    WRITE = 1
    FINANCIAL = 2
    DESTRUCTIVE = 3


class DataClass(IntEnum):
    """Sensitivity of data. Used to decide whether data may leave the local machine."""
    PUBLIC = 0
    INTERNAL = 1
    PERSONAL = 2
    FINANCIAL = 3


@dataclass(frozen=True)
class Principal:
    """A verified caller: which application, on behalf of which user."""
    app_id: str
    user_id: str
    scopes: frozenset = frozenset()


class ArcError(Exception):
    """Base class. `code` is stable and safe to return to clients."""
    code = "error"

    def __init__(self, message: str = "", **detail: Any):
        super().__init__(message or self.code)
        self.detail = detail


class AuthError(ArcError):
    code = "unauthenticated"


class PermissionDenied(ArcError):
    code = "permission_denied"


class ValidationError(ArcError):
    code = "invalid_request"


class QuotaExceeded(ArcError):
    code = "quota_exceeded"


class ModelUnavailable(ArcError):
    code = "model_unavailable"


class ToolUnavailable(ArcError):
    """A tool exists as a contract but no real provider is connected."""
    code = "tool_unavailable"


class ConfirmationError(ArcError):
    code = "confirmation_failed"


class MediaRejected(ArcError):
    code = "media_rejected"


@dataclass
class ChatRequest:
    messages: list
    temperature: float = 0.2
    max_tokens: int = 512
    json_mode: bool = False
    data_class: DataClass = DataClass.INTERNAL
    purpose: str = "chat"


@dataclass
class ChatResult:
    text: str
    model: str
    backend: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cached: bool = False
    cost: float = 0.0
    extra: dict = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """Cheap token estimate used only when a backend does not report usage."""
    return max(1, len(text) // 4) if text else 0
