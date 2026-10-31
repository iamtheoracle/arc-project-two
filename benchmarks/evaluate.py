"""Reproducible human-rated benchmark scoring and fail-closed release gate.

This runner scores supplied evaluator records. It does not pretend to judge model
quality automatically; subjective cases still require blinded human evaluation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class BenchmarkInputError(ValueError):
    pass


def evaluate(catalogue: dict[str, Any], ratings: dict[str, Any],
             min_average: float = 3.0) -> dict[str, Any]:
    cases = catalogue.get("cases")
    records = ratings.get("results")
    metadata = ratings.get("metadata")
    if not isinstance(cases, list) or not cases:
        raise BenchmarkInputError("Benchmark catalogue must contain non-empty cases")
    if not isinstance(records, list):
        raise BenchmarkInputError("Ratings must contain a results list")
    if not isinstance(metadata, dict):
        raise BenchmarkInputError("Ratings must contain run metadata")

    required_metadata = ("commit", "dataset_version", "prompt_version",
                         "model_provider", "evaluator_version")
    missing = [key for key in required_metadata
               if not isinstance(metadata.get(key), str) or not metadata[key].strip()]
    if missing:
        raise BenchmarkInputError("Missing run metadata: " + ", ".join(missing))

    case_by_id = {}
    for case in cases:
        case_id = case.get("id") if isinstance(case, dict) else None
        if not isinstance(case_id, str) or not case_id or case_id in case_by_id:
            raise BenchmarkInputError("Catalogue contains an invalid or duplicate case ID")
        case_by_id[case_id] = case

    rated = {}
    for record in records:
        if not isinstance(record, dict):
            raise BenchmarkInputError("Each rating must be an object")
        case_id = record.get("case_id")
        if case_id not in case_by_id:
            raise BenchmarkInputError(f"Unknown case ID: {case_id}")
        if case_id in rated:
            raise BenchmarkInputError(f"Duplicate rating for case: {case_id}")
        score = record.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 4:
            raise BenchmarkInputError(f"Score for {case_id} must be an integer from 0 to 4")
        critical_failure = record.get("critical_failure", False)
        if not isinstance(critical_failure, bool):
            raise BenchmarkInputError(f"critical_failure for {case_id} must be boolean")
        notes = record.get("notes", "")
        if not isinstance(notes, str):
            raise BenchmarkInputError(f"Notes for {case_id} must be text")
        rated[case_id] = {
            "case_id": case_id,
            "category": case_by_id[case_id].get("category", "uncategorized"),
            "risk": case_by_id[case_id].get("risk", "unknown"),
            "critical_case": bool(case_by_id[case_id].get("critical", False)),
            "score": score,
            "critical_failure": critical_failure,
            "notes": notes[:2000],
        }

    missing_cases = sorted(set(case_by_id) - set(rated))
    if missing_cases:
        raise BenchmarkInputError("Missing ratings for cases: " + ", ".join(missing_cases))

    rows = [rated[key] for key in case_by_id]
    average = sum(row["score"] for row in rows) / len(rows)
    failures = [
        row["case_id"] for row in rows
        if row["critical_failure"] or (row["critical_case"] and row["score"] < 3)
    ]
    passed = not failures and average >= min_average
    return {
        "schema_version": "1.0.0",
        "benchmark": catalogue.get("benchmark", "oracle-arc-platform"),
        "status": "passed" if passed else "failed",
        "release_gate": {
            "passed": passed,
            "minimum_average": min_average,
            "average_score": round(average, 4),
            "critical_failures": failures,
            "rule": "Any declared critical failure or critical-case score below 3 fails the gate, regardless of average.",
        },
        "metadata": {key: metadata[key] for key in required_metadata},
        "case_count": len(rows),
        "results": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default="benchmarks/cases.json")
    parser.add_argument("--ratings", required=True,
                        help="JSON file containing metadata and one score per case")
    parser.add_argument("--output", default="benchmark-report.json")
    parser.add_argument("--min-average", type=float, default=3.0)
    args = parser.parse_args()
    if not 0 <= args.min_average <= 4:
        parser.error("--min-average must be between 0 and 4")
    try:
        catalogue = json.loads(Path(args.catalogue).read_text(encoding="utf-8"))
        ratings = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
        report = evaluate(catalogue, ratings, args.min_average)
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, BenchmarkInputError) as exc:
        parser.exit(2, f"benchmark input error: {exc}\n")
    print(json.dumps(report["release_gate"], ensure_ascii=False))
    return 0 if report["release_gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
