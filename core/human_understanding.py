"""Human-understanding and adaptive communication policy for Oracle Arc.

This module shapes communication. It does not diagnose users, infer intelligence,
or imitate errors in a user's writing.
"""
from __future__ import annotations

from typing import Any

HUMAN_UNDERSTANDING_PROMPT = """Human understanding and communication rules:
- Always write correct, natural, grammatically sound English unless the user asks for another language or a deliberate style.
- Adapt the complexity of the explanation, not the quality of the language. A user who writes with spelling, grammar, or vocabulary errors must still receive polished English.
- Prefer plain, familiar words, short sentences, and one idea at a time when that will make the answer easier to understand.
- Never imitate, reproduce, mock, or point out a user's spelling or grammar errors unless they explicitly ask for language correction.
- Do not confuse simple language with low intelligence. Be respectful and never talk down to the user.
- Explain unfamiliar terms in context. Use concrete examples and memorable comparisons when they genuinely help.
- Adapt detail, tone, and examples to relevant user-provided preferences and conversation context. Do not force interests into unrelated answers.
- Treat inferred preferences as uncertain. Do not claim to know a user's thoughts, feelings, abilities, or private life. Ask when an assumption materially affects the answer.
- Use only context supplied in the current conversation or explicitly saved/authorized profile information. Do not imply access to private chats, friends, feeds, devices, or activity that has not been connected and authorized.
- The same underlying accuracy, safety, and respect apply to every user, regardless of writing style or English proficiency.
"""

VALID_DETAIL_LEVELS = {"simple", "balanced", "detailed"}
VALID_TONES = {"natural", "warm", "playful", "professional"}


def normalize_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    """Return a safe, bounded profile with conservative defaults."""
    profile = profile or {}
    detail = profile.get("detail_level", "simple")
    tone = profile.get("tone", "natural")
    interests = profile.get("interests", [])
    if detail not in VALID_DETAIL_LEVELS:
        detail = "simple"
    if tone not in VALID_TONES:
        tone = "natural"
    if not isinstance(interests, list):
        interests = []
    clean_interests = list(dict.fromkeys(
        item.strip()[:80] for item in interests
        if isinstance(item, str) and item.strip()
    ))[:30]
    return {
        "detail_level": detail,
        "tone": tone,
        "interests": clean_interests,
    }


def build_human_context(profile: dict[str, Any] | None = None) -> str:
    """Build a prompt section from explicit, owner-controlled preferences."""
    normalized = normalize_profile(profile)
    lines = [
        "Communication preferences (owner-provided; use only when relevant):",
        f"- Explanation detail: {normalized['detail_level']}.",
        f"- Conversation tone: {normalized['tone']}.",
    ]
    if normalized["interests"]:
        lines.append(
            "- Interests that may be used for relevant examples or conversation: "
            + ", ".join(normalized["interests"]) + "."
        )
    lines.append(
        "These preferences guide communication; they do not limit the user's "
        "abilities or define their identity. Do not force an interest into every answer."
    )
    return "\n".join(lines)
