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


## Specialist agent architecture: BUD, SPARK, ORACLE and ORBITS

The intended user-facing experience has four coordinated specialist roles. These are logical agent identities and responsibilities, not a claim that four independently running agents are already implemented.

- **BUD — Companion and coordinator:** the everyday conversational entry point. BUD listens, responds naturally, helps users think things through, explains things in accessible language, and routes work to the appropriate specialist. BUD should not force every conversation into a task or pretend to be human.
- **SPARK — Memory and continuity:** manages permitted personal context, preferences, goals and experiences. Spark owns memory lifecycle, provenance, correction, expiry and deletion. Other agents receive only the minimum memory scope explicitly granted for a task; Spark's private store is not globally shared.
- **ORACLE — Reasoning and problem-solving:** handles research, analysis, planning, factual questions, decisions and complex problem-solving through the shared model gateway.
- **ORBITS — Visual intelligence:** handles image understanding, visual analysis, design and supported creative workflows. It receives only the inputs and permissions needed for the requested visual task.

### Coordination and trust rules

1. Every agent has a stable agent ID, version, declared capabilities and least-privilege permissions.
2. Agents call the shared Oracle Arc service interface; they do not each hold provider credentials or the owner's master API key.
3. The model may propose delegation, but policy outside the model authorizes it. Agent role or conversational trust never grants security authority.
4. Delegation carries a scoped task envelope: requesting agent, target agent, purpose, allowed data references, permitted actions, deadline and correlation ID.
5. Spark memory access is explicit and auditable. BUD, Oracle and Orbits do not receive blanket access to private memories.
6. Tool execution remains subject to the secure execution boundary and exact-action approval rules. No agent can bypass tool policy.
7. Agent outputs are untrusted inputs to the receiving agent and must be validated before consequential use.
8. The user can understand which agent is handling a task, stop delegation and control saved personal context.
9. If a specialist is unavailable, BUD should explain the limitation and offer a safe alternative rather than inventing a completed action.

### Agent evaluation requirements

The benchmark must test BUD's conversational fit and routing, Spark's memory isolation and lifecycle, Oracle's reasoning and calibration, Orbits' visual task handling, and cross-agent delegation. Critical cases include unauthorized memory access, privilege escalation through delegation, prompt injection in agent outputs, duplicate execution, cancellation and partial failure. A successful handoff must preserve task context without expanding permissions.

**Implementation status:** a first registry and BUD-to-ORACLE routing policy exist. BUD currently delegates using deterministic intent matching for clear specialist requests; model-selected planning, service identities, SPARK and ORBITS runtimes, and end-to-end multi-agent orchestration remain incomplete.


## Agent registry and connector implementation baseline

The first registry implementation provides:
- Registered agent identities for BUD, ORACLE, SPARK and ORBITS. BUD and ORACLE are enabled; SPARK and ORBITS remain disabled until their specialist runtimes exist.
- BUD and ORACLE chat routes through a shared registry, with explicit and conservative automatic BUD-to-ORACLE delegation.
- Ordered Ollama connectors with per-connector failure cooldown and fallback to separately configured hosts through \`ORACLE_ARC_OLLAMA_FALLBACK_HOSTS\`.
- Session connector interface with ordered fallback. SQLite primary and optional independent SQLite backup are wired; mirrored writes use idempotency event IDs and reads/writes can fall back to the backup.
- Metadata-only plugin catalogue and an explicit allowlist for the reviewed calculator built-in. Calculator execution requires a rootless Podman worker with no network, read-only root filesystem, dropped capabilities, non-root UID, resource limits and a hard timeout. Arbitrary plugin file discovery is removed; file and system plugins are not executable.
- Authenticated registry, plugin catalogue and agent chat endpoints.

This is an initial single-process registry and connector layer, not yet a distributed agent control plane. Connector health is learned from request failures, not an active readiness probe. A fallback Ollama URL is useful only if the operator provisions a separate healthy service with the selected model. Session replication is synchronous application-level mirroring, not consensus or automatic recovery from loss of both stores; place the backup on independent infrastructure and test restore procedures. The calculator now runs in a rootless Podman container, but host runtime hardening, image provenance, deployment integration and adversarial testing remain release requirements. Third-party plugins, persistent cross-process circuit state, service identities, and model-selected planning remain follow-up work.

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

The repository is currently a single-owner FastAPI/Ollama/SQLite foundation with optional remote model adapters, a first BUD/ORACLE registry, optional mirrored session backup, and a rootless Podman calculator worker. It is not yet a production multi-tenant platform, fully provider-independent gateway, semantic memory engine, complete multimodal system or autonomous distributed multi-agent system. These are target capabilities, not claims about shipped code.


## Agent control plane and execution verification

The current control-plane foundation now assigns every agent chat a durable task ID and records queued, running, succeeded or failed state in SQLite. Task records retain source agent, target agent, declared required capabilities, connector/provider selection and a sanitized failure code; they do not store prompt or response text. When the independent session backup is configured, task metadata is mirrored there and status reads fall back to it if the primary database is unavailable. Owners can inspect a task through the authenticated `GET /v1/agent-tasks/{task_id}` endpoint. Dispatch checks that the target agent declares every requested capability before invoking a connector, and connector status exposes failure count, last exception type and cooldown remaining.

This remains a single-service control plane: task state and connector health are not yet shared across replicas, there is no lease/claim protocol or durable distributed queue, and task cancellation/replay/reconciliation are not implemented. Do not deploy multiple API replicas expecting coordinated task ownership until those pieces exist.

CI now installs rootless Podman, builds the worker image, runs the actual calculator container, and verifies effective UID, zero capabilities, no-new-privileges, no default network route and read-only root mount before the Python test suite. The worker receives request input through an explicitly interactive stdin pipe. A successful image build alone is not considered proof of worker execution; the real runtime smoke test must pass. Recovery tests make the primary SQLite path inaccessible at the filesystem level and verify that both conversation messages and task status continue through the independent backup.
