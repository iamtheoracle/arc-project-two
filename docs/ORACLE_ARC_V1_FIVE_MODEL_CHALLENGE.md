# ORACLE-ARC V1 — Five-Model Challenge Strategy
**Status:** V1 product and engineering target  
**Scope:** THE ORACLE-ARC only  
**Principle:** Win through orchestration, evidence, verification and execution—not by pretending that five model calls create five times the intelligence.

## 1. V1 ambition

The first public-quality version should feel like a serious intelligence system, not a thin chat interface. Its defining capability is to solve difficult tasks using a coordinated panel of specialist models, then challenge and verify their work before presenting a result.

The target is to outperform a five-model ensemble on a defined, published, repeatable task suite. This is a measurable engineering goal, not a claim that Oracle-Arc will beat every five-model team on every possible task.

## 2. The central design: ORACLE COUNCIL

Use up to five specialist model roles. These are roles, not five permanently hard-coded providers.

1. **ORACLE / Lead planner** — understands the request, defines success criteria, decomposes the task and chooses which specialists are needed.
2. **THE BUILDER** — develops solutions, code, plans, drafts and concrete implementation proposals.
3. **THE SKEPTIC** — independently searches for errors, hidden assumptions, counterexamples, risks and alternative explanations.
4. **THE RESEARCHER** — retrieves external evidence when freshness or factual sourcing matters; maps each important claim to sources.
5. **THE VERIFIER** — checks outputs against task criteria, evidence, tests, calculations and policy. It must be allowed to reject the proposed answer.

A separate **ORCHESTRATOR** controls budgets, parallelism, retries, model selection, deadlines and data permissions. A deterministic validation layer checks things models should not be trusted to self-certify: arithmetic, schemas, code tests, permissions, citations, required fields and task state.

The five roles may use different models, different providers, or the same model with genuinely different tasks. Provider diversity is preferred when it improves independence, but must be measured rather than assumed.

## 3. How the council works

### Stage A — Understand
- Parse the user's intent, constraints, risk, privacy level and freshness requirements.
- Ask one clarification only when an essential ambiguity blocks safe execution.
- Convert the request into explicit deliverables and acceptance tests.

### Stage B — Plan
- Lead planner creates a short plan and allocates roles.
- Orchestrator chooses models based on task capability, availability, privacy policy, latency and cost.
- Private local data stays local unless the owner explicitly authorizes a specific remote transfer.

### Stage C — Independent first passes
- Specialists receive the same task brief and only the context needed for their role.
- For high-stakes or difficult questions, at least two first-pass answers must be independently produced before panel discussion.
- Do not let one model's proposed answer contaminate every other specialist's first pass.
- Each response must expose assumptions, uncertainty and evidence needs.

### Stage D — Adversarial challenge
- Skeptic identifies the strongest failure modes and constructs counterexamples.
- Researcher checks material external claims against actual sources.
- Builder revises the proposal against the objections.
- The system preserves disagreements rather than forcing artificial consensus.

### Stage E — Verification
- Verifier checks each requirement and the support for each important claim.
- Run deterministic checks where possible: unit tests, static checks, calculations, schema validation, source-link checks and policy checks.
- If verification fails, send a bounded correction request to the responsible specialist.
- Maximum rounds, tokens, elapsed time and tool calls are enforced. No infinite debate loops.

### Stage F — Final decision
Return the best supported answer, not the most popular answer.
- Separate confirmed facts, sourced claims, inference, assumptions and unknowns.
- Explain unresolved disagreement when material.
- Show sources and tests where applicable.
- State what was and was not actually executed.
- Ask for approval before consequential external actions.

## 4. Why this can beat a five-model group

A naive group often has five weaknesses:
- Correlated models repeat the same wrong assumption.
- Majority voting rewards popularity rather than truth.
- Discussion can anchor independent reviewers.
- Long debate consumes tokens without improving the result.
- Models can claim success without running tests or checking evidence.

Oracle-Arc's advantage must come from:
- Independent first-pass reasoning.
- Deliberate role specialization.
- Evidence retrieval and claim-to-source matching.
- Adversarial counterexamples.
- Deterministic verification.
- Explicit uncertainty and disagreement handling.
- A measurable stopping rule.
- Durable task state and recovery.
- Better task routing, not maximum model count.

Five models are a maximum panel, not a requirement for every request. Simple requests should use one model. A difficult request may use two or three. Use all five only when expected quality gain justifies latency, cost and privacy exposure.

## 5. Model gateway requirements

Implement a provider-neutral adapter with a common request/response contract:
- Provider and model identifier.
- Capability declarations: text, vision, audio, structured output, tool calling, context window.
- Availability and health.
- Timeout and cancellation.
- Input/output token accounting and estimated cost where available.
- Retry policy and rate-limit handling.
- Data classification and provider permission.
- Model version and configuration provenance.
- Normalized errors without leaking secrets.

Routing must be capability-based and policy-aware. Never send private memory or documents to a remote model just because it scored higher. The owner must be able to disable each remote provider and use local-only mode.

## 6. V1 feature boundary

### Must ship in V1
- Single-model local mode remains functional.
- Provider-neutral model gateway.
- Configurable specialist roles.
- Council execution with bounded parallel calls.
- Independent first-pass responses.
- Skeptic challenge and structured objections.
- Verifier with explicit pass/fail reasons.
- Deterministic checks for supported output types.
- Source and uncertainty tracking.
- Per-task budget, timeout, cancellation and trace.
- Owner-controlled provider permissions.
- Visible task history and audit events.
- Graceful fallback when one or more models are unavailable.

### Do not claim as complete until built and tested
- Human-level general intelligence.
- Universal superiority over all model ensembles.
- Perfect factual accuracy or hallucination elimination.
- Fully autonomous execution without approval.
- Secure plugin sandbox until OS isolation is demonstrated.
- Persistent personal understanding until SPARK provenance, correction and deletion are complete.
- Multimodal mastery until ORBITS modality-specific tests pass.

## 7. Evaluation: prove the winning card

Create a locked benchmark set with at least these task classes:
1. Multi-step reasoning and planning.
2. Difficult coding and repository debugging.
3. Research with fresh evidence and citations.
4. Mathematical and structured-data correctness.
5. Long-context synthesis across multiple documents.
6. Adversarial prompt injection and conflicting instructions.
7. Memory recall, correction and deletion.
8. Tool-use reliability and safe refusal.
9. Interrupted workflow recovery and idempotency.
10. Complex real-world tasks with explicit acceptance criteria.

Compare at least four systems:
- Qwen2.5-7B local single-model baseline.
- Strongest single model available for the task.
- Naive five-model baseline (independent answers plus simple vote or merge).
- Oracle-Arc Council (specialized roles, challenge and verification).

Keep the same user task, evidence availability, tool permissions and output rubric. Run multiple trials where outputs are stochastic. Report pass rate, critical error rate, evidence correctness, instruction adherence, latency, token use, cost, privacy exposure and failure recovery.

### V1 acceptance targets

These are proposed gates to be validated and adjusted after a pilot; they are not existing results:
- At least 10 percentage points higher task pass rate than the naive five-model baseline on the locked composite benchmark, with uncertainty intervals reported.
- No increase in critical safety or privacy failures; zero unauthorized consequential actions in the test suite.
- Every benchmark claim has a reproducible run manifest.
- Every external factual claim in research tasks is linked to a source that actually supports it.
- Failed verification is surfaced; no false completion claims.
- Local-only mode passes the full privacy-routing suite.
- Budget and deadline limits are never exceeded silently.

If the council does not beat the baseline, do not market the claim. Diagnose which tasks lose and improve routing, independence, verification or model choice.

## 8. Implementation sequence

1. Inspect and stabilize current LocalLLM adapter and test contracts.
2. Add normalized provider interface and model capability registry.
3. Add provider configuration with secrets outside source control.
4. Add role prompts and typed JSON response schemas.
5. Add council orchestrator with bounded parallel execution and per-task budget.
6. Add independent first-pass storage and provenance.
7. Add skeptic challenge and disagreement representation.
8. Add deterministic verifier interface and first checks.
9. Add trace, cancellation, retry and graceful degradation.
10. Add benchmark runner and locked task suite.
11. Run local Qwen baseline, naive panel and council comparison.
12. Add remote providers only through explicit owner consent and data-classification rules.

Do not start by wiring five API keys into the current chat endpoint. Build the gateway and policy boundary first. Do not allow council agents to invoke arbitrary tools directly; they propose actions, and the central policy/approval layer authorizes execution.

## 9. Current status and honest boundary

This document defines the intended V1 strategy. It does not mean the council, provider gateway, five-model routing, independent verifier or benchmark suite has already been implemented. The repository currently has a local Ollama adapter configured for Qwen2.5-7B and the earlier foundation described in the intelligence blueprint. Implementation must proceed in small, tested commits.
