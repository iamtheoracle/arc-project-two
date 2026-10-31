# Oracle Arc Master Architecture

**Status:** Architecture baseline — 2026-10-30  
**Scope:** THE ORACLE-ARC only. This document excludes UNIBUD, AVCU, Vantoris X Money and other projects.

## Mission

Oracle Arc is an intelligence operating system: a secure, provider-independent platform coordinating models, memory, human understanding, specialist agents, tools and multimodal capabilities. It should be conversational and adaptive without weakening accuracy, consent, privacy or security.

The platform must not claim consciousness, human experience, guaranteed correctness or uncontrolled self-improvement. Improvements must be measured and released through controlled evaluation.

## 1. Secure execution foundation

**Current state (2026-10-31):** Arbitrary plugin discovery/import is removed. Only the reviewed calculator is executable, through a rootless Podman worker with no network, read-only root filesystem, dropped capabilities, non-root identity, resource limits and a hard timeout. Tool approval remains default-deny. Third-party integration artifacts can only be staged inertly after digest verification; activation remains blocked because no reviewed integration-specific runtime adapter is configured. Host hardening, image provenance, adversarial escape testing and production deployment review remain open.

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

**Current state (2026-10-31):** Ollama remains the default local adapter. Fixed-endpoint OpenAI-compatible adapters for OpenRouter, Groq and Gemini are registered only when server-side credentials exist. BUD and ORACLE connectors have ordered Ollama host fallback and provider fallback. Timeouts and failure cooldowns exist, but task-aware privacy routing, streaming normalization, usage budgets, cancellation, active readiness checks and live provider validation remain incomplete. Private context must not be sent to a remote provider without an explicit deployment policy.

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

**Current state (2026-10-31):** SQLite stores owner-managed memories, profile preferences and explicit boundaries; a bounded set of recent memories is added to prompts as untrusted context. Memory lifecycle endpoints exist, but semantic retrieval, structured provenance/confidence/expiry, derived-index deletion, encryption at rest and scoped multi-agent memory grants are not implemented. SPARK remains disabled.

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

**Current state (2026-10-31):** A detailed conversational policy, owner-controlled profile and boundaries, and a request-aware reasoning reliability standard are wired into BUD, ORACLE and the direct chat route. The request classifier adds different checks for time-sensitive, high-stakes, quantitative, technical and comparison requests. This is prompt guidance plus deterministic request classification, not an independent fact verifier or proof of reasoning quality. Most tests verify policy contracts and normalization; live model behaviour still needs blinded evaluation.

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

**Current state (2026-10-31):** The scenario catalogue contains 18 cases across conversation, human understanding, memory, reasoning, secure execution, provider gateway, privacy and agent coordination. A human-rating evaluator now validates complete case coverage, run metadata and 0–4 scores; any declared critical failure or critical-case score below 3 fails the release gate regardless of average. The evaluator records supplied ratings; it does not automatically judge model quality. Full blinded runs, holdout management and baseline reports remain to be completed.

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


## Durable task queue, worker leases and transactional outbox

The agent task store now supports atomic task claims using SQLite immediate transactions, worker ownership, lease renewal, expiry recovery and bounded retries. A worker can renew only its own live lease; a task completion can be accepted only from the current lease owner. Expired work is requeued until its attempt limit, after which it is marked failed with a sanitized failure code. Owners can mark queued or running tasks cancelled through an authenticated endpoint. A running model HTTP call is not forcibly interrupted yet; the API prevents its late result from being persisted.

Task creation and lifecycle changes append an outbox event in the same SQLite transaction. Outbox consumers claim events with expiring leases and acknowledge them after delivery. This is at-least-once delivery: consumers must deduplicate using the event ID and must not assume exactly-once external side effects. Expired deliveries are retried up to a bounded attempt count and then marked dead-letter for operator review. Stale workers cannot acknowledge after their lease expires.

The API's current chat path claims a short-lived lease, renews it during long model calls, and performs the model call synchronously. The queue/outbox primitives are suitable for concurrent claimers sharing one transactional database, but no independent worker daemon, broker, distributed scheduler, or cross-host database is deployed yet. Separate SQLite files on different hosts do not coordinate claims. The configured backup database is a recovery mirror, not a distributed consensus system.


Owner-only operational routes now expose recent task records and queue counters, including pending outbox age and dead-letter count. These endpoints deliberately expose task metadata and failure codes, not user prompts or model responses.


## 8. Implementation ownership and integration selection

**New implementation:** `core/implementation_planner.py` provides a transparent, deterministic first-pass capability planner. The authenticated `POST /v1/implementation/plan` endpoint accepts a bounded plain-language description and returns a structured recommendation.

### Ownership model

- BUD is the coordinator and user-facing point of contact.
- ORACLE owns technical analysis, architecture, implementation planning and validation.
- SPARK is the specialist for explicitly permitted memory and continuity changes.
- ORBITS is the specialist for visual understanding and creative workflows.
- A task may involve more than one specialist, but the primary owner is explicit.

### Integration selection

The planner separately identifies required capabilities and candidate plugins, extensions and connectors. It labels recommendations as uninstalled/unconfigured and reports whether a specialist is registered and enabled. It does not claim that a connector is healthy merely because its name appears in the plan.

### Security and limits

- The planner is deterministic keyword/capability matching, not autonomous model-selected planning.
- Recommendations do not import, install, enable, approve or execute anything.
- A trusted manifest, provenance review, version pinning, permissions review, data-handling review, sandbox validation and health checks are required before activation.
- External side effects remain behind owner approval and existing tool policy.
- Disabled SPARK and ORBITS remain disabled until their runtimes and tests are ready.
- Keyword matching can miss context or over-match terms; the plan is advisory and must be reviewed for ambiguous or high-impact work.

**Validation required:** unit tests cover technical/integration routing, visual and memory specialist selection, disabled-agent visibility, empty input, authentication and the no-side-effects contract. The endpoint must remain owner-authenticated.


## 9. Trusted integration manager and independent workers

### Manifest manager

`core/integrations.py` treats plugin, extension and connector manifests as untrusted data until validated. Publisher HMAC signatures are checked against server-side trust keys. The inspector validates IDs, semantic versions, app-version compatibility, declared capabilities, permission allowlists, risk classification and artifact SHA-256 digest. It never imports, downloads or executes manifest code.

Candidate selection requires a valid signature, compatible app version, all requested capabilities and permissions within the configured allowlist. Eligible candidates are ordered by lower declared risk, fewer permissions and then known health status. Declared risk is a publisher claim and is not a substitute for artifact review or sandboxing.

Health remains `unknown` unless a trusted integration-specific health adapter is wired. A health URL in a manifest is metadata only; it is not fetched. This prevents arbitrary manifest URLs from creating an SSRF path.

### Approval and audit

The owner-authenticated API exposes catalog inspection, exact-manifest approval requests, approval/rejection decisions, and audit history. Approval binds to integration ID, version and canonical manifest digest. Any changed manifest requires a new approval. The database stores the request, decision maker, reason and timestamps in separate approval and audit tables.

Approval is not activation. The owner-authenticated `POST /v1/integrations/{integration_id}/install` endpoint now supports a narrow inert-staging step: it requires approval for the exact manifest digest, reads a pre-positioned artifact from a private server-side staging directory, checks the artifact SHA-256 while copying, applies owner-only file permissions, atomically refuses replacement of an existing version, and appends an audit event. Artifact size is capped at 25 MiB; symlink inputs and invalid identifiers are rejected. The artifact is stored as opaque bytes only: archives are not extracted, modules are not imported, no process is launched and no runtime permission is granted. This is not code installation or activation.

The artifact must be pre-positioned by a trusted operator at `<integration-id>-<version>.artifact`. Configure `ORACLE_ARC_INTEGRATION_ARTIFACT_STAGING_DIR` (default `data/integration-artifact-staging`) and `ORACLE_ARC_INTEGRATION_INSTALL_DIR` (default `data/integrations`). Arbitrary manifest URLs are never fetched.

A separate activation-approval table and owner-authenticated request/decision routes now add a second decision after inert staging. The request verifies the current signed manifest, the original installation approval and the staged artifact digest. Activation decisions are bound to the same integration ID, version and manifest digest and are written to the audit log. The activation endpoint deliberately returns HTTP 409 and records the blocked attempt until an integration-specific isolated runtime adapter is reviewed and configured; approval does not execute code or grant permissions.

Still required before real activation: a reviewed per-integration runtime adapter, rootless isolated installer/executor, narrowly scoped runtime permission broker, integration-specific health checks, revocation/deactivation, rollback, and end-to-end sandbox tests.

### Independent agent worker

`core/agent_worker.py` is a separate process that claims durable tasks, renews expiring leases, dispatches through the configured agent registry and persists results only while it owns the lease. `POST /v1/agent-tasks/submit` queues work for this process. Existing synchronous chat remains unchanged.

Workers and API must share the same transactional database. Current SQLite queue coordination is single-host/shared-volume only; multi-host deployment requires PostgreSQL or another shared transactional store. Worker credentials and network permissions must be scoped independently from owner API credentials. The task payload contains conversation context and must be protected as sensitive data at rest and in backups.


## Reasoning reliability implementation baseline

A request-aware reliability policy is wired into all current chat entry points. It classifies the latest user request into general, time-sensitive, high-stakes, quantitative, technical or comparison work and adds task-specific requirements for evidence, uncertainty, arithmetic checks, code inspection, rollback and professional escalation. It instructs the model to provide concise explanations and evidence summaries rather than private chain-of-thought.

This layer is intentionally not described as a fact checker: deterministic wording classification cannot prove that a model's answer is true. Current evidence still requires an actual trusted source or an honest disclosure that live verification is unavailable. Calculations need independent recomputation; code changes need executed tests; subjective behaviour needs blinded human ratings. The benchmark scoring runner enforces complete case coverage and prevents a critical regression from being hidden by a high average.

**Known limits:** the classifier is heuristic and may miss unusual phrasing or over-classify ambiguous requests. Model self-review is not independent verification. Live Ollama inference, external provider quality, production latency, user-facing behaviour and real-world generalization are not established by unit tests.
