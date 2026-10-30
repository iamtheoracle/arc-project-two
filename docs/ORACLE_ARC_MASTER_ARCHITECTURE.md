# Oracle Arc Master Architecture

**Status:** Architecture baseline — 2026-10-30  
**Scope:** THE ORACLE-ARC only. This document excludes UNIBUD, AVCU, Vantoris X Money and other projects.

## Mission

Oracle Arc is an intelligence operating system: a secure, provider-independent platform coordinating models, memory, human understanding, specialist agents, tools and multimodal capabilities. It should be conversational and adaptive without weakening accuracy, consent, privacy or security.

The platform must not claim consciousness, human experience, guaranteed correctness or uncontrolled self-improvement. Improvements must be measured and released through controlled evaluation.

## 1. Secure execution foundation

**Current state:** Owner approval exists and tools are denied by default, but Python plugins are dynamically imported and execute in the API process. Approval is not isolation. This is a security blocker.

**Target design**
- Separate the control plane (identity, policy, approvals, audit) from the execution plane (tool workers).
- Never dynamically import untrusted or merely discovered plugin files in the API process.
- Use explicit, versioned tool manifests, unique names, strict JSON Schema validation, bounded input/output sizes and declared permissions.
- Execute tools in disposable isolated workers/containers with non-root identity, read-only base filesystem, narrow mounts, restricted network egress, CPU/memory/process limits and hard deadlines.
- Give tools short-lived scoped capabilities, never the owner master key.
- Bind consequential-action approval to the exact tool, arguments, target and expiry.
- Treat tool output, files, retrieved content and model-generated arguments as untrusted.
- Return sanitized errors to the model; keep diagnostic detail in protected logs.
- Record actor, user/tenant, agent, tool/version, approval, arguments digest, outcome, timestamps and correlation ID in an append-only audit trail.
- Add replay protection, idempotency and cancellation/recovery for long-running actions.

**Release gate:** No arbitrary plugin code executes in the API process. Negative tests prove malformed schemas, unapproved calls, expired approvals, path traversal, network escape and resource exhaustion are rejected. Until isolated execution is deployed and tested, tools must remain disabled or limited to explicitly trusted built-ins.

## 2. Provider-independent model gateway

**Current state:** The model layer is a direct Ollama wrapper. The API selects one server-configured model. A provider registry, capability model and fallback policy are not implemented.

**Target design**
- Define a stable provider contract for chat, streaming, tool calls, cancellation, usage, errors and health.
- Implement adapters independently, starting with Ollama and later adding OpenRouter, Gemini, Groq, Anthropic and others.
- Keep credentials server-side; never expose provider keys to clients or agents.
- Route by task capability, quality target, privacy classification, latency, availability and cost budget.
- Use explicit fallback policies. Never silently send private context to a less trusted provider.
- Normalize tool calls, finish reasons, token usage and errors.
- Apply timeouts, bounded retries, circuit breakers, concurrency limits, cancellation and per-user budgets.
- Separate liveness from readiness; readiness checks must not leak secrets.
- Log route reason, provider/model version, latency, usage and outcome while minimizing prompt retention.

**Release gate:** Contract tests pass against a fake provider and each enabled adapter. Timeout, outage, malformed response, cancellation and fallback tests pass. Private-context routing is policy-tested.

## 3. Spark memory engine

**Current state:** SQLite stores owner-managed memory records; the API injects a bounded set of recent memories into the prompt. Semantic retrieval, lifecycle management and scoped multi-agent access are not implemented.

**Target design**
- Memory classes: working/current-turn, episodic events, semantic facts, procedural preferences, goals/projects and explicit boundaries.
- Every memory has owner/scope, source/provenance, timestamps, confidence, sensitivity, expiry/retention, status and correction/deletion history.
- Separate candidate extraction from persistence. Uncertain observations are hypotheses, not facts.
- Require confirmation for sensitive or consequential inferred memories; do not infer sensitive traits for personalization.
- Retrieve by semantic relevance plus recency, importance, scope, confidence and permissions; do not inject all recent memories.
- Detect conflicts and preserve provenance. A newer statement does not automatically erase older facts without determining whether the change is temporary or permanent.
- Support inspection, correction, export and deletion, including derived indexes and caches.
- Enforce least-privilege agent access; Spark-private memory is not automatically shared with every specialist.
- Add retention/expiry, backup/restore, encryption-at-rest strategy and deletion verification.

**Release gate:** Tests cover relevance, cross-user isolation, agent scopes, stale memories, contradictions, confidence, consent, deletion propagation and restore.

## 4. Human understanding as a measurable capability

**Current state:** A detailed conversational policy and profile normalization exist. Most adaptation is prompt-based; tests largely verify prompt content and normalization rather than observed model behaviour.

**Target design**
- Build a structured, turn-local interpretation of intent, task, conversational mode, tone cues, uncertainty, desired detail and support needs.
- Represent interpretations as tentative hypotheses with evidence, confidence and expiry. Do not diagnose or assign permanent personality labels.
- Use explicit feedback and confirmed preferences to update durable profile data.
- Adapt naturally across casual conversation, listening, tutoring, serious work, playful exchanges, planning and concise answers.
- Tutor patiently and without shame; try alternate explanations when needed.
- Preserve correct, natural language without imitating user errors.
- Respect boundaries and autonomy; do not pressure continued conversation.
- Evaluate actual behaviour with scenario tests and blinded human ratings, not prompt-string assertions alone.

**Release gate:** A measured scenario suite covers conversational naturalness, context accuracy, patience, correction quality, tone appropriateness, boundary respect, calibration and non-manipulation. Critical safety failures cannot be averaged away.

## 5. Oracle Arc platform benchmark

**Current state:** Unit and API tests exist (52 passed on commit 5af99bbc96f1ed1f7f7e1729e97b2e5cd0df875a), but no end-to-end benchmark measures the five systems together.

**Target design**
- Versioned, reproducible scenarios with fixed inputs, expected properties and scoring rubrics.
- Separate deterministic tests, model-graded tests and blinded human evaluation.
- Track quality, security, reliability, latency, usage/cost and regression rate.
- Compare model/provider configurations on identical scenarios.
- Maintain a protected holdout set to reduce benchmark overfitting.
- Record code commit, prompt version, model/provider/version, dataset version, run configuration and evaluator version.
- Require regression gates before promotion; report uncertainty where sample sizes support it.
- Never treat benchmark scores as proof of general intelligence or guaranteed superiority.

**Release gate:** Every release produces a versioned report. Critical security tests are pass/fail gates, not averages. Quality gains cannot conceal privacy, factuality or reliability regressions.

## Cross-cutting architecture

- **Identity:** separate human, tenant, agent, service and tool identities.
- **Policy:** authorization is enforced outside the model.
- **Data:** tenant isolation, encryption, retention, provenance and deletion propagation.
- **Observability:** structured logs, traces, metrics, correlation IDs and redaction.
- **Reliability:** idempotency, concurrency control, timeouts, cancellation, recovery and backups.
- **Evaluation:** unit, integration, adversarial, model-behaviour and end-to-end tests.
- **Governance:** versioned prompts, policies, tools, models and memory schemas; reviewed migrations and rollback.

## Implementation sequence

1. Secure execution and request/conversation integrity.
2. Provider contract and gateway, retaining Ollama as the first adapter.
3. Spark memory schema, retrieval and governance.
4. Structured human-understanding signals and behavioural evaluation.
5. End-to-end benchmark runner, release gates and baseline reports.
6. Expand multi-agent orchestration and multimodal engines only on this foundation.

## Current truth and non-claims

The repository is currently a single-owner FastAPI/Ollama/SQLite foundation. It is not yet a production multi-tenant platform, isolated plugin runtime, provider-independent gateway, semantic memory engine, multimodal system or autonomous multi-agent society. These are target capabilities, not claims about shipped code.
