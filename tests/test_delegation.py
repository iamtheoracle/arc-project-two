from core.delegation import select_agent


def test_research_and_analysis_tasks_route_to_oracle():
    assert select_agent("bud", "Please research this topic") [0] == "oracle"


def test_everyday_chat_stays_with_bud():
    assert select_agent("bud", "Can you keep me company?") == ("bud", None)


def test_non_bud_agent_is_never_rerouted():
    assert select_agent("oracle", "Please research this") == ("oracle", None)
