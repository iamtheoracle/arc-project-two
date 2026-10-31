from core.implementation_planner import plan_implementation


def test_technical_implementation_selects_oracle_and_safe_integration_recommendations():
    plan = plan_implementation("Build and debug a GitHub API connector and run tests")
    assert plan["coordinator"] == "bud"
    assert plan["primary_agent"] == "oracle"
    assert "reasoning" in plan["required_capabilities"]
    assert "integration" in plan["required_capabilities"]
    assert {item["id"] for item in plan["recommended_connectors"]} >= {"github", "integration-api"}
    assert plan["execution_authorized"] is False
    assert all(item["auto_install"] is False for item in plan["recommended_extensions"])


def test_visual_and_memory_work_routes_to_specialists_without_enabling_them():
    visual = plan_implementation("Analyze this image and create a visual diagram",
                                 {"bud": True, "oracle": True, "orbits": False, "spark": False})
    assert visual["primary_agent"] == "orbits"
    assert visual["agents"][0]["registered_and_enabled"] is False

    memory = plan_implementation("Review saved memory and recall my preference",
                                 {"bud": True, "oracle": True, "spark": False})
    assert memory["primary_agent"] == "spark"
    assert memory["agents"][0]["registered_and_enabled"] is False


def test_empty_description_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        plan_implementation("  ")
