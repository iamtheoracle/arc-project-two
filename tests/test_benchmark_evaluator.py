import pytest

from benchmarks.evaluate import BenchmarkInputError, evaluate


def catalogue():
    return {
        "benchmark": "oracle-arc-platform",
        "cases": [
            {"id": "normal-1", "category": "reasoning", "risk": "medium", "critical": False},
            {"id": "security-1", "category": "security", "risk": "critical", "critical": True},
        ],
    }


def ratings(normal=4, security=4, critical_failure=False):
    return {
        "metadata": {
            "commit": "abc123",
            "dataset_version": "1.0.0",
            "prompt_version": "reasoning-v1",
            "model_provider": "ollama:qwen2.5:7b",
            "evaluator_version": "human-rubric-v1",
        },
        "results": [
            {"case_id": "normal-1", "score": normal},
            {"case_id": "security-1", "score": security, "critical_failure": critical_failure},
        ],
    }


def test_benchmark_passes_when_average_and_critical_cases_pass():
    report = evaluate(catalogue(), ratings())
    assert report["status"] == "passed"
    assert report["release_gate"]["average_score"] == 4.0


def test_critical_failure_overrides_high_average():
    report = evaluate(catalogue(), ratings(4, 4, critical_failure=True))
    assert report["status"] == "failed"
    assert report["release_gate"]["critical_failures"] == ["security-1"]


def test_low_critical_case_score_fails_release_gate():
    report = evaluate(catalogue(), ratings(4, 2))
    assert report["status"] == "failed"
    assert "security-1" in report["release_gate"]["critical_failures"]


def test_average_threshold_fails_without_critical_failure():
    report = evaluate(catalogue(), ratings(2, 3), min_average=3.0)
    assert report["status"] == "failed"
    assert report["release_gate"]["critical_failures"] == []


def test_missing_case_rating_is_rejected():
    data = ratings()
    data["results"].pop()
    with pytest.raises(BenchmarkInputError, match="Missing ratings"):
        evaluate(catalogue(), data)


def test_duplicate_and_unknown_case_ids_are_rejected():
    data = ratings()
    data["results"].append(data["results"][0])
    with pytest.raises(BenchmarkInputError, match="Duplicate rating"):
        evaluate(catalogue(), data)
    data["results"][-1] = {"case_id": "unknown", "score": 4}
    with pytest.raises(BenchmarkInputError, match="Unknown case"):
        evaluate(catalogue(), data)


def test_invalid_scores_and_missing_metadata_are_rejected():
    data = ratings()
    data["results"][0]["score"] = True
    with pytest.raises(BenchmarkInputError, match="integer from 0 to 4"):
        evaluate(catalogue(), data)
    data = ratings()
    del data["metadata"]["commit"]
    with pytest.raises(BenchmarkInputError, match="Missing run metadata"):
        evaluate(catalogue(), data)
