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
