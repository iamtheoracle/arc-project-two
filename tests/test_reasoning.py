from core.reasoning import assess_request, build_reasoning_context


def test_general_request_gets_baseline_evidence_and_logic_checks():
    profile = assess_request("Explain how photosynthesis works")
    assert profile.task_type == "general"
    assert "unsupported certainty" in " ".join(profile.response_requirements)


def test_current_request_requires_fresh_sources_and_date_awareness():
    profile = assess_request("What is the latest price today?")
    assert profile.needs_current_evidence is True
    context = build_reasoning_context("What is the latest price today?")
    assert "fresh, trustworthy sources" in context


def test_high_stakes_request_adds_limits_and_human_escalation():
    profile = assess_request("Can you diagnose this medical symptom?")
    assert profile.risk_level == "high"
    context = build_reasoning_context("Can you diagnose this medical symptom?")
    assert "qualified human help" in context
    assert "guaranteed financial outcome" in context


def test_quantitative_request_requires_units_and_recalculation():
    profile = assess_request("Calculate the percentage and total")
    assert profile.needs_calculation_check is True
    assert "independently recompute" in " ".join(profile.response_requirements)


def test_technical_request_requires_real_validation_and_rollback_awareness():
    profile = assess_request("Debug this API deployment failure")
    assert profile.needs_code_validation is True
    assert "rollback" in " ".join(profile.response_requirements)


def test_comparison_requires_same_criteria_and_tradeoffs():
    profile = assess_request("Compare option A versus option B")
    assert profile.task_type == "comparison"
    assert "same criteria" in " ".join(profile.response_requirements)


def test_reasoning_contract_does_not_request_private_chain_of_thought():
    context = build_reasoning_context("Explain a difficult idea")
    assert "Do not reveal private chain-of-thought" in context
    assert "concise explanation" in context


def test_source_requests_require_claim_level_corroboration():
    profile = assess_request("Research this claim and provide sources")
    assert profile.needs_source_corroboration is True
    context = build_reasoning_context("Research this claim and provide sources")
    assert "supports the specific claim" in context


def test_sensitive_context_requires_privacy_review():
    profile = assess_request("Help me handle my API key and personal data")
    assert profile.needs_privacy_review is True
    assert "never request passwords" in " ".join(profile.response_requirements)


def test_consequential_actions_require_explicit_confirmation():
    profile = assess_request("Transfer money to this account")
    assert profile.needs_human_confirmation is True
    assert "explicit user authorization" in " ".join(profile.response_requirements)


def test_multiple_safety_dimensions_apply_at_the_same_time():
    profile = assess_request("Today, calculate and transfer my investment funds")
    assert profile.needs_current_evidence is True
    assert profile.needs_calculation_check is True
    assert profile.needs_source_corroboration is True
    assert profile.needs_human_confirmation is True
    assert profile.risk_level == "high"
