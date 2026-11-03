# THE ORACLE-ARC — Unified Capability Fabric
**Status:** Product architecture and implementation specification  
**Scope:** THE ORACLE-ARC only  
**Principle:** Absorb the strongest capabilities of the AI ecosystem into one coherent, owner-controlled intelligence environment. Do not recreate a pile of vendor dashboards or make the product dependent on one provider.

## 1. Product vision

Oracle-Arc should feel like the best capabilities of the modern AI ecosystem have migrated into one private environment. The owner asks for an outcome; Oracle chooses and coordinates the capabilities needed to produce it.

The owner should not need to know whether a task used a language model, search index, browser, document parser, vector store, code runner, image model, transcription engine, or evaluation service. Oracle presents one coherent workflow, one identity, one permission system, one task history, and one verified result.

This is a capability architecture, not a bundle of vendor logos.

## 2. What “premium and easy to use” means

The experience must provide:
- One command surface for asking, researching, creating, learning, and executing.
- A capability catalogue with plain-language descriptions, examples, availability, privacy classification, and permission status.
- Automatic task routing based on quality, capability, privacy, latency, reliability, and budget.
- A consistent interaction contract regardless of the underlying provider.
- Clear status: local, connected, unavailable, requires owner connection, requires approval, or paid usage may apply.
- One task timeline showing plan, selected capabilities, evidence, approvals, outputs, verification, and recovery.
- Sensible defaults; advanced controls remain available without overwhelming the normal experience.
- A local-first fallback for core reasoning and personal continuity.

“Premium” means high-quality capabilities and a polished experience. It does not mean bypassing provider subscriptions, API billing, rate limits, terms, or authorization. Oracle must never imply a paid API is free or silently incur charges.

## 3. The Oracle-native capability layers

### A. Intelligence and model fabric
A provider-neutral gateway normalizes local and remote models behind one contract. It maintains a capability registry for reasoning, coding, structured output, tool calling, long context, vision, audio, and other modalities. It records provider/model identity, version, availability, limits, latency, token use, cost estimates, data handling and permission.

Initial path:
1. Keep Ollama as the default local inference path.
2. Add a normalized provider interface without changing the public chat contract.
3. Add provider adapters one at a time, each with contract tests and explicit owner configuration.
4. Add capability-aware routing only after adapters and data policy are tested.
5. Preserve local-only mode as a first-class operating mode.

Do not hard-code a permanent five-vendor panel. A model is a replaceable engine, not the identity of Oracle.

### B. ORACLE COUNCIL
Specialist roles work as one coordinated team:
- Lead planner: interprets intent, constraints and success criteria.
- Builder: produces candidate solutions and artifacts.
- Researcher: finds and records evidence when external knowledge is required.
- Skeptic: attacks assumptions, looks for counterexamples and identifies failure modes.
- Verifier: checks evidence, tests, calculations, permissions and completion.

The orchestrator decides how many roles are justified. Simple work uses one model; complex work may use multiple independent models. Independent first passes precede debate where appropriate. The verifier can reject a result. Consensus is not proof.

### C. Knowledge and research fabric
A single research workflow can combine approved search providers, source-specific connectors, document libraries and owner-provided files. Every material claim should retain source identity, publisher, date, retrieval time, excerpt/locator and claim relationship. Conflicting sources and stale evidence must be visible.

Retrieved content is untrusted data. It cannot change system policy, reveal secrets, approve tools or instruct Oracle to ignore the owner.

### D. Browser and computer-work fabric
Provide a controlled browser capability for reading pages, navigating approved sites, extracting information and completing permitted workflows. A separate computer-use capability may operate graphical interfaces where a supported integration exists.

Browser actions must be scoped, auditable and isolated. Read-only inspection is the default. Purchases, payments, account changes, external messages, submissions, deletion and other consequential actions require explicit approval immediately before execution. Never claim a browser action succeeded without a returned result.

### E. Creation and multimodal fabric — ORBITS
A unified artifact pipeline handles documents, spreadsheets, presentations, code, images, diagrams, audio and video where the configured engines support them. It must preserve editable source and structured data when required, not return only a flattened preview. Each artifact records its inputs, transformations, model/tool provenance and validation status.

### F. Memory and personal continuity — SPARK
Memory is a first-class owner-controlled service, not a prompt dump. It supports typed records, provenance, confidence, sensitivity, expiry, conflict handling, review, correction, export and deletion. Semantic indexes and caches are derived data and must be rebuildable and covered by deletion tests. Imported or inferred facts must never silently become owner-confirmed facts.

### G. Execution and workflow fabric
A durable task engine converts approved plans into bounded steps with checkpoints, deadlines, idempotency, cancellation, retries, recovery and completion verification. Powerful tools run in restricted workers, not in the API process. Each capability declares its input schema, side effects, required permissions, network access, resource ceilings and risk class.

### H. Evaluation and observability fabric
Every important workflow should be measurable. Record redacted traces for routing decisions, model calls, tool calls, evidence, verification, latency, budget and failure state. Maintain repeatable evaluations for accuracy, instruction following, prompt injection, memory correctness, tool authorization, recovery, latency and cost. Evaluation tools do not get unrestricted access to private data.

### I. Owner control plane
A single private control centre provides:
- Connected providers and services.
- Local/remote routing preferences.
- Capability catalogue and health.
- Model selection and per-task budget.
- Permissions, approvals and revocations.
- Memory review, correction, export and deletion.
- Task history, checkpoints and audit.
- Data retention, backup and restore status.
- Local-only mode and emergency disconnect.

## 4. One experience, not ten separate products

The owner sees a small number of outcome-oriented entry points:
1. **Ask** — explanations, reasoning and everyday help.
2. **Research** — investigate questions and produce evidence-backed reports.
3. **Create** — produce and edit artifacts.
4. **Learn** — explain, teach, practise and assess understanding.
5. **Do** — plan and execute approved workflows.
6. **My Intelligence** — memory, preferences, active projects and personal knowledge.
7. **Control** — connected capabilities, privacy, permissions, costs and system health.

These are views into one system, not separate agents with separate memories or policies. ORACLE coordinates them; SPARK supplies governed continuity; ORBITS handles multimodal work; EXECUTION performs authorized actions; VERIFIER checks outcomes.

## 5. Capability contract

Every integration must implement a common manifest:
- Stable capability ID and version.
- Human-readable name, purpose and examples.
- Input/output schema and supported content types.
- Required model or service capabilities.
- Local/remote classification and data destinations.
- Permission scopes and side-effect declaration.
- Authentication method and secret storage reference (never the secret itself).
- Rate limits, timeout, concurrency and resource limits.
- Cost model or “unknown/not supplied” status.
- Health/readiness and normalized error states.
- Audit and provenance requirements.
- Cancellation, retry and idempotency behavior.
- Test suite and supported version range.

No integration is exposed as ready until its contract, failure behavior, permissions and tests are implemented.

## 6. Routing and selection policy

For each task, Oracle creates a task profile:
- Intent and deliverable.
- Risk and side-effect level.
- Data classification and privacy boundary.
- Required modalities and capabilities.
- Freshness/evidence requirements.
- Quality target and verification method.
- Deadline and budget.

The router selects the smallest adequate set of capabilities. Its priority order is:
1. Permission and privacy compliance.
2. Required capability and reliability.
3. Evidence and verification quality.
4. Owner's local/remote preference.
5. Latency and availability.
6. Cost and budget.

Never route private data remotely solely because a remote model appears stronger. Do not fan out to five models by default. Do not treat model self-reported confidence as calibrated truth.

## 7. Security and commercial boundaries

- Local inference remains available without remote provider keys.
- Every remote provider is opt-in, separately enabled and revocable.
- Show which data categories may leave the device before enabling a provider.
- Minimize outbound context; send only task-relevant data.
- Never send SPARK memories, files or conversation history to remote services by default.
- Store credentials in a server-side secret store or environment; never in source code, browser bundles, logs or task traces.
- Show estimated costs where reliable; identify unknown charges and provider billing separately.
- Respect API terms, rate limits, account entitlements and regional restrictions.
- Do not scrape or bypass authentication, paywalls, quotas or usage controls.
- A connected API key does not grant blanket permission to perform actions in the provider's account.
- Disconnecting a provider must stop new calls and provide a clear policy for retained provider-side data.

## 8. Failure behavior

The product must degrade gracefully:
- If a remote model is down, use an eligible local model or explain the limitation.
- If search is unavailable, distinguish existing knowledge from fresh research.
- If a browser session expires, stop and request reconnection.
- If a tool fails halfway, preserve the checkpoint and report exactly what completed.
- If verification fails, do not present the task as verified.
- If the budget or deadline is exhausted, stop safely and show the partial result.
- If no permitted capability can perform the task, explain what connection or approval is needed.

## 9. V1 implementation order

### Gate 0 — Stabilize the existing core
Resolve current PR/CI state, keep the local chat path working, validate request limits and rate limiting, add SQLite migration/backup coverage, and keep unsandboxed in-process plugins disabled. Build an isolated worker before enabling powerful tools.

### Gate 1 — Capability foundation
Create typed capability manifests, a registry, normalized errors, provider configuration, health reporting, secret references and contract tests. Do not add many vendor adapters yet.

### Gate 2 — Model gateway
Refactor the current LocalLLM behind a stable interface. Preserve Ollama as the default. Add one optional remote adapter only after explicit configuration, privacy tests and provider contract tests. Add capability-aware routing and local-only enforcement.

### Gate 3 — Council and verifier
Implement typed role outputs, independent first passes, bounded parallelism, adversarial review, deterministic checks, trace, cancellation, budgets and graceful degradation.

### Gate 4 — Research and knowledge
Implement source records, claim-to-source mapping, freshness and conflict handling. Add one search adapter behind the capability contract and test prompt-injection resistance.

### Gate 5 — Durable execution
Implement restricted workers, approval checkpoints, idempotency, recovery, audit and completion verification. Only then enable meaningful write-capable tools.

### Gate 6 — SPARK and ORBITS
Implement governed memory retrieval and deletion semantics; then add multimodal/document/artifact adapters with typed outputs and traceability.

### Gate 7 — Unified owner experience
Expose Ask, Research, Create, Learn, Do, My Intelligence and Control as a coherent interface with consistent navigation, task timeline and capability catalogue.

## 10. Acceptance criteria

The system is not considered to have absorbed a capability merely because a vendor SDK is installed. Each capability must pass:
- Manifest and schema validation.
- Authentication and secret-handling tests.
- Permission-denial and revocation tests.
- Data-egress and local-only tests.
- Timeout, rate-limit, retry and cancellation tests.
- Prompt-injection and untrusted-output tests where applicable.
- Audit/provenance checks.
- Cost and budget enforcement where applicable.
- Deterministic task verification.
- Failure and recovery tests.

The product claim that Oracle-Arc outperforms a five-model team remains an evaluation target. Prove it on a locked benchmark with reproducible runs; never claim universal superiority from architecture alone.

## 11. Current status — important

This document is the product and engineering specification. It does not mean these integrations or experiences are already implemented. The current repository still has a local Ollama adapter and the previously documented foundation. The next code milestone is the capability contract and model gateway, not wiring a collection of premium API keys directly into the chat endpoint.
