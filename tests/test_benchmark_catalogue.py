import json
from pathlib import Path


def test_benchmark_catalogue_is_versioned_and_has_unique_cases():
    path = Path(__file__).parents[1] / "benchmarks" / "cases.json"
    catalogue = json.loads(path.read_text(encoding="utf-8"))

    assert catalogue["schema_version"] == "1.0.0"
    assert catalogue["benchmark"] == "oracle-arc-platform"
    assert catalogue["scoring"]["critical_failures_override_average"] is True

    cases = catalogue["cases"]
    case_ids = [case["id"] for case in cases]
    assert len(case_ids) >= 10
    assert len(case_ids) == len(set(case_ids))
    assert all(case.get("category") and case.get("task") for case in cases)
    assert any(case.get("critical") for case in cases)


def test_benchmark_covers_all_five_foundations():
    path = Path(__file__).parents[1] / "benchmarks" / "cases.json"
    catalogue = json.loads(path.read_text(encoding="utf-8"))
    categories = {case["category"] for case in catalogue["cases"]}

    assert {
        "secure_execution",
        "model_gateway",
        "spark_memory",
        "human_understanding",
        "conversation",
    }.issubset(categories)
