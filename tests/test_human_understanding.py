from core.human_understanding import (
    HUMAN_UNDERSTANDING_PROMPT,
    build_human_context,
    normalize_profile,
)


def test_language_quality_is_never_lowered_to_match_user_errors():
    assert "Always write correct, natural, grammatically sound English" in HUMAN_UNDERSTANDING_PROMPT
    assert "Never imitate, reproduce, mock" in HUMAN_UNDERSTANDING_PROMPT
    assert "Adapt the complexity of the explanation, not the quality of the language" in HUMAN_UNDERSTANDING_PROMPT


def test_profile_defaults_to_simple_natural_communication():
    assert normalize_profile(None) == {
        "detail_level": "simple",
        "tone": "natural",
        "interests": [],
    }


def test_profile_normalizes_and_bounds_interests():
    profile = normalize_profile({
        "detail_level": "invalid",
        "tone": "playful",
        "interests": [" Football ", "Anime", "Football", "", 12, "x" * 100],
    })
    assert profile["detail_level"] == "simple"
    assert profile["tone"] == "playful"
    assert profile["interests"] == ["Football", "Anime", "x" * 80]


def test_context_uses_interests_as_optional_examples_not_identity():
    context = build_human_context({
        "detail_level": "balanced",
        "tone": "warm",
        "interests": ["football", "anime"],
    })
    assert "football, anime" in context
    assert "Do not force an interest into every answer" in context
    assert "do not limit the user's abilities" in context
