"""Reliability policy for Oracle Arc's reasoning and answer construction.

This module does not claim to verify facts by itself. It classifies the kind of care a
request needs and gives the model a consistent, testable answer-quality contract.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ReasoningProfile:
    task_type: str
    risk_level: str
    needs_current_evidence: bool
    needs_calculation_check: bool
    needs_code_validation: bool
    response_requirements: tuple[str, ...]


_CURRENT = re.compile(
    r"\\b(latest|current|currently|today|yesterday|tomorrow|this week|"
    r"recent|newest|now|price|exchange rate|availability|open now|"
    r"who is the present|as of \\d{4})\\b",
    re.IGNORECASE,
)
_HIGH_STAKES = re.compile(
    r"\\b(medical|medicine|medication|diagnos|symptom|treatment|"
    r"legal|lawyer|lawsuit|contract|tax|investment|investing|loan|"
    r"credit|banking|financial|suicide|self.?harm|emergency|"
    r"security breach|exploit|vulnerability|production data)\\b",
    re.IGNORECASE,
)
_CODE = re.compile(
    r"\\b(code|coding|program|debug|bug|exception|stack trace|"
    r"repository|github|api|database|sql|deploy|deployment|"
    r"function|class|test|compiler|build)\\b",
    re.IGNORECASE,
)
_CALC = re.compile(
    r"\\b(calculate|calculation|how many|how much|percentage|percent|"
    r"convert|conversion|sum|average|interest rate|total|estimate)\\b",
    re.IGNORECASE,
)
_COMPARE = re.compile(r"\\b(compare|versus|vs\\.?|better|best|trade.?off|pros and cons)\\b", re.IGNORECASE)


def assess_request(text: str) -> ReasoningProfile:
    """Return conservative response requirements for a user request."""
    value = text if isinstance(text, str) else ""
    current = bool(_CURRENT.search(value))
    high_stakes = bool(_HIGH_STAKES.search(value))
    code = bool(_CODE.search(value))
    calculation = bool(_CALC.search(value))
    comparison = bool(_COMPARE.search(value))

    if high_stakes:
        task_type, risk = "high_stakes", "high"
    elif code:
        task_type, risk = "technical", "moderate"
    elif calculation:
        task_type, risk = "quantitative", "moderate"
    elif comparison:
        task_type, risk = "comparison", "ordinary"
    elif current:
        task_type, risk = "time_sensitive", "ordinary"
    else:
        task_type, risk = "general", "ordinary"

    requirements = [
        "Answer the actual question first; do not substitute a nearby easier question.",
        "Separate user-provided facts, verified evidence, assumptions, and estimates.",
        "Check the proposed answer for contradictions, missing steps, and unsupported certainty.",
        "If a key detail is missing, ask one focused question or state a bounded assumption.",
        "Never invent citations, sources, tests, tool results, calculations, or completed actions.",
        "Do not reveal private chain-of-thought; provide a concise explanation, method, or evidence summary instead.",
    ]
    if current:
        requirements.extend([
            "Current or changing facts require fresh, trustworthy sources; disclose when live verification is unavailable.",
            "Attach dates and units to time-sensitive values and distinguish publication dates from event dates.",
        ])
    if high_stakes:
        requirements.extend([
            "Use a cautious, evidence-led answer and make the limits of the available information explicit.",
            "Do not present general information as a personal professional diagnosis, legal opinion, or guaranteed financial outcome.",
            "Identify urgent danger signals and recommend qualified human help when appropriate.",
            "Do not execute consequential actions or treat a model-generated recommendation as authorization.",
        ])
    if calculation:
        requirements.extend([
            "Show the formula and units for material calculations, then independently recompute or sanity-check the result.",
            "State assumptions and avoid false precision when inputs are estimates.",
        ])
    if code:
        requirements.extend([
            "Inspect the actual relevant code and call sites before proposing changes when repository access is available.",
            "Prefer the smallest safe change; consider compatibility, security, failure paths, migrations, and rollback.",
            "Distinguish code written from code executed; report only tests that actually ran and their exact outcome.",
        ])
    if comparison:
        requirements.append(
            "Compare options against the same criteria, state trade-offs, and explain what would change the recommendation."
        )
    return ReasoningProfile(
        task_type=task_type,
        risk_level=risk,
        needs_current_evidence=current,
        needs_calculation_check=calculation,
        needs_code_validation=code,
        response_requirements=tuple(requirements),
    )


def build_reasoning_context(text: str) -> str:
    """Build a compact, request-specific reliability contract for the model."""
    profile = assess_request(text)
    lines = [
        "ORACLE ARC REASONING AND RELIABILITY STANDARD (apply silently):",
        f"- Request class: {profile.task_type}; risk level: {profile.risk_level}.",
        f"- Fresh evidence required: {'yes' if profile.needs_current_evidence else 'not indicated by wording'}.",
        f"- Calculation check required: {'yes' if profile.needs_calculation_check else 'no'}.",
        f"- Code validation required: {'yes' if profile.needs_code_validation else 'no'}.",
    ]
    lines.extend(f"- {item}" for item in profile.response_requirements)
    lines.append(
        "Before finalizing, run a brief private quality check: relevance, factual support, "
        "logic, arithmetic, safety, completeness, and clarity. If a check cannot be completed, "
        "say so rather than implying that it passed."
    )
    return "\\n".join(lines)
