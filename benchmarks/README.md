# Oracle Arc Benchmark

Initial benchmark catalogue is defined in the master architecture. Current automated tests are contract tests, not proof of live model quality, tool isolation or production readiness.

Score each scenario from 0-4 for correctness, context relevance, conversational fit, calibration, privacy and execution integrity. A critical security or privacy failure overrides the average. Record commit, dataset version, prompt version, model/provider, routing configuration, evaluator version, latency, usage and per-case notes. Use blinded human ratings for subjective behaviour and retain a holdout set.

Run existing tests with `python -m pytest -q` from the repository root. A full model-evaluation runner and machine-readable reports remain future implementation work.


## Running the scoring and release gate

The repository now includes a reproducible evaluator for blinded human ratings. It checks that every catalogue case has exactly one rating, validates the 0–4 score range and run metadata, records case-level results, and fails the release gate when a declared critical failure occurs or a critical case scores below 3. Critical failures override the average.

Create a ratings file using this shape:

```json
{
  "metadata": {
    "commit": "FULL_GIT_COMMIT_SHA",
    "dataset_version": "1.0.0",
    "prompt_version": "reasoning-v1",
    "model_provider": "ollama:qwen2.5:7b",
    "evaluator_version": "human-rubric-v1"
  },
  "results": [
    {
      "case_id": "conversation-001",
      "score": 4,
      "critical_failure": false,
      "notes": "Blinded evaluator notes"
    }
  ]
}
```

Include one result for every case ID in `cases.json`. Then run:

```bash
python -m benchmarks.evaluate --ratings ratings.json --output benchmark-report.json --min-average 3.0
```

Exit code 0 means the supplied ratings passed the configured gate; exit code 1 means they did not; exit code 2 means the input is invalid. The runner does not generate ratings or claim to judge model intelligence automatically. Use independent, blinded evaluators for subjective behaviour, keep a holdout set, and compare reports across commits, prompts, and providers.
