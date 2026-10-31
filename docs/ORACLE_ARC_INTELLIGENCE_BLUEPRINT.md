# THE ORACLE-ARC — Intelligence System Blueprint

## Product promise
THE ORACLE-ARC is a private, owner-controlled intelligence environment. It is not a generic chatbot or a collection of unrelated agents. Its purpose is to help its owner understand, decide, create, learn, research, and execute work with continuity and verifiable results.

The system remains local-first. Ollama is the first inference provider. Cloud services may be optional adapters, never a hidden requirement for core memory, reasoning, or control.

## Non-negotiable principles
1. Owner sovereignty: one explicit owner identity; owner-controlled memory, tools, exports, deletion, backups, and policy.
2. Truth before performance theatre: distinguish observed facts, sourced claims, model inference, assumptions, and unknowns. Never fabricate tool use, research, memory, or completion.
3. Local-first: Ollama first, behind a provider-neutral interface.
4. Least authority: tools denied by default, narrowly scoped, separately approved, revocable, and audited.
5. Untrusted input stays untrusted: retrieved documents, web pages, memories, and tool output cannot rewrite policy or grant permissions.
6. Human agency: support human judgement and relationships; never cultivate dependency or take consequential actions without explicit authorization.
7. Measurable capability: every major intelligence claim has repeatable tests and observable acceptance criteria.
8. Recoverability: migrations, backups, checkpoints, and failure recovery are designed before critical workflows are trusted.

## Unified architecture

### ORACLE — reasoning and research
Coordinates intent understanding, planning, research, specialist capabilities, and synthesis. Preserves evidence/inference boundaries and reports uncertainty.

### SPARK — personal continuity and memory
Manages explicit preferences, stable facts, active projects, goals, decisions, learned skills, and temporary context. Memory records carry type, provenance, confidence, timestamps, optional expiry, sensitivity, and owner visibility. Inferred memories remain marked inferred until confirmed. Conflicts are surfaced, not silently overwritten. Retrieval is relevance-ranked and token-budgeted. Deletion must remove canonical records and derived indexes/caches.

### ORBITS — creation and multimodal work
Coordinates document understanding, image/audio inputs, diagrams, structured data, and generated artifacts. Uses typed artifact contracts and preserves source references. Visual output must not replace editable source or structured data when those are required.

### EXECUTION — permissioned tools and workflows
Turns approved plans into bounded actions. Each action declares purpose, inputs, scope, side effects, risk, timeout, and approval requirement. Runs in a separate restricted worker, not the API process. Every action has an auditable outcome and recovery strategy.

### VERIFIER — independent quality and safety checks
Checks claims against cited evidence, validates calculations deterministically, checks output contracts and permission boundaries, and verifies task completion. It can disagree with the planner and request correction.

### MODEL GATEWAY — local-first inference abstraction
Supports Ollama first, with capability discovery, deadlines, structured-output validation, health state, and explicit model configuration. Routing is explainable and testable. No provider silently receives private memory or documents.

### KNOWLEDGE AND RESEARCH
Research connectors are optional, individually permissioned sources. Retrieved material is stored with source identity, publisher, retrieval time, publication time when available, excerpt/hash, and trust notes. Search results are evidence candidates, not instructions. Claim-to-source alignment and conflicting evidence are first-class records.

### CONTROL PLANE
A private owner interface exposes memory review, tool approvals, connected sources, task status, model health, audit history, data export/deletion, backup status, and settings. No hidden background action is invisible to the owner.

## Core request lifecycle
1. Authenticate the owner and enforce request, payload, and concurrency limits.
2. Classify intent, risk, freshness needs, and whether research or a tool is required.
3. Retrieve only relevant memories and task state, preserving provenance and source boundaries.
4. Build a bounded plan with success criteria and explicit assumptions.
5. Perform read-only reasoning/research first; request approval before consequential side effects.
6. Validate tool arguments, run tools in restricted workers with deadlines/resource ceilings, and capture audit events.
7. Verify factual claims, calculations, output structure, and completion evidence.
8. Return sources, uncertainty, actions taken, and actions not taken.
9. Save only useful memory candidates under owner policy; do not silently make every conversation permanent.

## Memory data contract
Each memory supports a stable identifier and content; type (preference, profile fact, project, goal, decision, skill, event, temporary context); provenance (owner-explicit, owner-confirmed, inferred, imported); confidence and rationale; created/updated/last-used/optional expiry timestamps; sensitivity and retrieval policy; optional source conversation/document and conflict/supersession links; lifecycle state (candidate, active, disputed, expired, deleted).

Memory extraction and retrieval are separate services. Retrieval supports exact keyword matching before semantic search is introduced. Semantic indexes are derived data and must be rebuildable and deletable.

## Research and evidence contract
For every material external claim, retain source identity, source type, publisher, publication date if available, retrieval date, relevant excerpt/locator, and the claim supported. Report disagreements and stale evidence. Do not imply a source proves a claim it does not address. If no reliable source is found, say so.

## Execution safety contract
- Plugin allowlisting is not a security boundary. Arbitrary plugin code must not run in the API process in the final design.
- Use a dedicated worker with an unprivileged OS identity, restricted filesystem, no ambient secrets, network denied by default, CPU/memory/process/time limits, and narrow RPC.
- Validate JSON Schema and enforce per-tool policy server-side.
- Separate tool discovery, owner approval, per-run authorization, and execution.
- Require explicit confirmation for irreversible, financial, identity, external communication, or destructive actions.
- Make retries idempotent where possible. Record intent, approval, execution, result, and verification separately.
- Never log credentials or unrestricted sensitive arguments.

## Reliability and privacy requirements
- API: rate limiting, body-size limits, authentication hardening, safe errors, request IDs, bounded concurrency.
- Inference: explicit connect/read deadlines, cancellation where supported, bounded context, clear model-unavailable status.
- Storage: transactional migrations, WAL/concurrency tests, integrity checks, encrypted backups, restore drills, export/delete coverage.
- Operations: readiness separate from liveness; structured redacted logs; resource/latency metrics; no secrets in logs.
- Data: local database protection, optional encryption at rest with a recoverable key strategy, retention controls, complete deletion semantics.
- Supply chain: dependency scanning, secret scanning, minimal CI permissions, reproducible tests.

## Capability roadmap and exit gates

### Phase 0 — Harden the existing core
Implement request limits, rate limiting, inference deadlines, lifecycle management, SQLite migration/concurrency guarantees, owner session protections, and API security review. Replace in-process plugin execution with an isolated worker before enabling powerful tools.
Exit gate: adversarial API tests pass; oversized/concurrent requests are bounded; model timeout returns a safe recoverable response; no unapproved tool executes; worker isolation is demonstrated, not merely documented.

### Phase 1 — SPARK memory engine
Introduce versioned migrations and typed/provenance-aware memory. Add candidate extraction, owner review, relevance retrieval, conflict handling, expiry, export, and full deletion of canonical and derived records.
Exit gate: recall precision/recall and fabricated-memory rate are measured; deletion/correction tests prove stale records cannot reappear.

### Phase 2 — ORACLE verified reasoning and research
Add structured plans, evidence records, source freshness, claim-to-source checks, deterministic calculations, contradiction detection, uncertainty reporting, and bounded correction loops.
Exit gate: benchmarks measure factual accuracy, citation support, uncertainty calibration, arithmetic correctness, and prompt-injection resistance.

### Phase 3 — Reliable EXECUTION
Add durable task records, states, checkpoints, idempotency keys, approval gates, restricted workers, retries, cancellation, recovery, and independent completion verification.
Exit gate: crash/restart and partial-failure tests prove actions are not duplicated and incomplete work is never reported complete.

### Phase 4 — Personal learning intelligence
Build owner-directed learning goals, skill maps, adaptive explanation depth, practice generation, progress evidence, and knowledge-gap tracking. Progress is based on demonstrated comprehension, not time spent or model praise.
Exit gate: repeatable assessments show whether explanations improve understanding and retention.

### Phase 5 — ORBITS multimodal and creation
Add document/image/audio ingestion, OCR/transcription adapters, artifact generation, editable structured outputs, and source traceability. Keep model and hardware requirements visible.
Exit gate: each modality has privacy controls, supported-format tests, and source-to-output traceability.

### Phase 6 — Advanced coordination
After foundations are stable, add specialist agent profiles, model routing, proactive suggestions, scheduled workflows, and optional integrations. Specialists remain subordinate to one owner policy and one verifier.
Exit gate: coordination measurably improves outcomes without increasing unsafe actions, privacy exposure, or unexplained cost/latency.

## Evaluation suite
Maintain versioned benchmark sets for memory precision/recall/correction/expiry/deletion; multi-step reasoning/planning; research freshness and claim/source alignment; numerical accuracy; authorization and sandbox escape attempts; prompt injection through user content, memory, documents, web pages, and tool results; task interruption/retry/idempotency/recovery; uncertainty calibration; learning comprehension/retention; latency/context use/memory footprint/resource use/stability.

Run fast deterministic CI tests on every change and a separately labelled live-Ollama evaluation on configured hardware. Report model, quantization, hardware, prompt-set version, and results. Mocked CI must never be presented as live-model validation.

## Immediate repository findings
1. The chat endpoint injects up to 30 recent memories as a flat prompt block; there is no type/provenance-aware retrieval or owner review of inferred memory.
2. LocalLLM constructs an Ollama client without explicit request deadlines or tested cancellation policy.
3. Plugin allowlisting and approval are useful gates, but handlers execute inside the API process; this is not isolation.
4. The API has no explicit rate limiter, request body cap, or inference concurrency budget.
5. Conversation requests and durable task execution are not separated; there is no task checkpoint/recovery engine.
6. CI mocks model responses; a separate live local-model evaluation is required.
7. SQLite migration versioning, WAL policy, concurrent writes, and backup/restore drills need explicit coverage.
8. Current memory injection is not semantic retrieval; do not label it as such.

## Scope discipline
Do not add every feature in one risky change. Build gated, reviewable milestones. Preserve the local-first API where practical, migrate data backward-compatibly, keep tools disabled by default, and never deploy publicly or enable consequential actions before security and operational acceptance tests pass.