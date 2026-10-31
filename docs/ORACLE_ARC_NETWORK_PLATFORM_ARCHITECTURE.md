# Oracle Arc — MY REALM Network Platform Architecture & Delivery Tracker

**Status:** Working architecture amendment and delivery tracker  
**Created:** 2026-10-31  
**Repository:** `iamtheoracle/arc-project-two`  
**Purpose:** Extend Oracle Arc from its current personal-core implementation into the shared, secure intelligence platform for MY REALM NETWORK without discarding existing work.

> This document is additive. It does not replace the existing personal-core, human-understanding, security-audit, unified-capability-fabric, or master-architecture documents. It records the network-level requirements that those documents did not fully cover.

## 1. Product identity and scope

Oracle Arc is the shared intelligence platform for MY REALM NETWORK applications. It is not a UNIBUD-only assistant and must not hard-code one product's identity, data model, safety rules, or workflows into the shared core.

Potential application consumers include UNIBUD, WAYWARD, SOULYNC, and future MY REALM products. A consumer is not considered integrated merely because it appears in a prompt, architecture diagram, connector catalogue, or environment variable. Each integration must have a reviewed contract, a configured adapter, permissions, tests, and an observable operational status.

Oracle Arc provides reusable intelligence infrastructure:
- Model/provider gateway and policy-aware routing.
- BUD conversational entry point and task coordinator.
- ORACLE reasoning, research, planning and problem-solving.
- SPARK permissioned memory and continuity.
- ORBITS visual understanding and supported creative workflows.
- CONCIERGE practical service discovery, booking research, appointment planning, travel coordination and workflow follow-through.
- Agent registry, task orchestration, capability contracts and evaluation.
- Tool execution and integration lifecycle controls.
- Identity, tenant isolation, audit, usage, reliability and security boundaries.

The specialist names describe logical responsibilities. They do not prove that every specialist is independently deployed or production-ready.

## 2. Non-negotiable architecture decisions

1. **One shared platform, isolated application contexts.** Shared infrastructure must never mean shared private data.
2. **Tenant and application scope are mandatory.** Every request, credential, session, memory, file, tool grant, task, audit event and usage record must carry an explicit owner and application scope.
3. **Fail closed.** Missing, ambiguous, expired or mismatched identity, tenant, app, permission or policy context must deny access.
4. **No implicit cross-app memory.** A memory created in one app is not visible to another app or agent unless a separate, explicit, revocable grant permits the minimum required fields for a stated purpose.
5. **No client authority.** Clients cannot choose arbitrary providers, models, tools, tenant IDs, roles, memory scopes or policy overrides.
6. **Product policy remains with the product.** Each consuming app owns its legal, age, consent, moderation, eligibility, financial and domain-specific rules. Oracle Arc enforces the supplied, authenticated policy context but does not replace product-side enforcement.
7. **No prompt-only security.** Prompts can guide model behaviour; server-side authorization and deterministic policy checks enforce access and actions.
8. **No silent provider downgrade.** Privacy classification, data residency, cost, capability and explicit fallback policy govern routing. Private context must not silently move to a less trusted provider.
9. **No unreviewed execution.** Model output, retrieved content, manifests, tool arguments and integration artifacts are untrusted until validated. Consequential side effects require scoped authorization and approval.
10. **Evidence before status claims.** Distinguish implemented, tested, live-verified, deployed and production-approved states.

## 3. Tenant and application identity model

The target request context should contain at minimum:

- `tenant_id`: owning organisation or isolated personal workspace.
- `application_id`: registered consuming application.
- `environment`: development, staging or production.
- `subject_id`: authenticated end-user or service principal.
- `actor_type`: user, application service, agent or operator.
- `session_id` / `conversation_id`: scoped interaction identifiers.
- `request_id` and `correlation_id`: traceability identifiers.
- `policy_version`: immutable policy snapshot used for the request.
- `capability_grants`: narrowly scoped permissions issued by the authorization layer.
- `data_classification`: public, internal, confidential or restricted, with product-specific extensions.
- `purpose` and `consent_reference`: why the data is being processed and the authority for it.

The client may provide a requested application context, but the server must derive or validate it against the authenticated credential. Never trust a client-supplied `tenant_id`, `subject_id`, role or capability grant.

### Credential model

- Issue separate credentials per application, environment and integration.
- Store secrets only in trusted server-side secret storage.
- Support expiry, rotation, revocation, least-privilege scopes and audit.
- Do not reuse the owner bootstrap secret as a consumer application's credential.
- Use service-to-service authentication for backend integrations; browser/mobile clients must not receive platform master secrets.
- Prefer short-lived scoped tokens or signed assertions for delegated work.
- Record credential identity and scope in every audit event without recording secret material.

### Data isolation

Every persistence query must scope by tenant and application as appropriate, and enforce ownership at the storage boundary. Add negative tests that deliberately attempt cross-tenant and cross-application reads, writes, enumeration, deletion, task retrieval, file access and tool execution.

For high-risk domains, use separate database schemas or databases where required by the threat model or contract. Row-level scope filters alone are not a substitute for defense in depth. Backups, exports, logs, caches, vector indexes, search indexes and analytics pipelines must preserve the same boundaries.

## 4. Core service boundaries

| Service | Owns | Must not own |
|---|---|---|
| Identity & Authorization | App registrations, service identities, scopes, grants, revocation, policy decisions | Product user profile as a universal identity record |
| Model Gateway | Provider adapters, routing, capability and usage normalization, privacy-aware dispatch | Product-specific user data ownership |
| BUD / Agent Orchestrator | Conversation coordination, specialist dispatch, task lifecycle | Unrestricted access to every specialist's data |
| ORACLE | Reasoning, research, analysis and planning | Authority to approve its own consequential actions |
| SPARK | Permissioned memory lifecycle, provenance, retrieval, expiry, correction and deletion | Automatic global memory sharing |
| ORBITS | Authorized visual inputs, visual analysis and creative task outputs | Unrequested access to user files or device media |
| Tool Control Plane | Manifests, policy, approvals, audit and capability grants | Direct execution of arbitrary plugin code |
| Isolated Execution Plane | Sandboxed, scoped, time-bounded tool workers | Owner master credentials or unrestricted host access |
| Integration Manager | App/connector manifests, compatibility, approval, staging, activation and revocation lifecycle | Treating a manifest's claims as proof of safety or health |
| Observability & Evaluation | Redacted telemetry, quality/security/reliability metrics and release evidence | Raw private prompts or cross-tenant analytics without a valid purpose |

## 5. Application integration contract

Each application integration must register and version a contract with:

- Application identity, owner and environment.
- Supported API version and compatibility window.
- Authentication method and key rotation procedure.
- Permitted capabilities and data classifications.
- Explicit inbound and outbound data fields.
- Purpose, consent and retention rules.
- Product policy adapter and enforcement responsibilities.
- Rate, concurrency, token and cost budgets.
- Timeout, retry, idempotency and cancellation behaviour.
- Webhook/event signature and replay protection, if applicable.
- Health/readiness checks and operational owner.
- Revocation, incident response and data-deletion procedure.

An integration lifecycle is:

1. **Discovered** — a candidate is known; no trust is implied.
2. **Reviewed** — source, publisher, permissions, data flow and risk are inspected.
3. **Approved** — an authorized owner approves an exact version/digest and declared scopes.
4. **Configured** — secrets, endpoint, policy and environment are set.
5. **Staged** — inert artifact or configuration is validated; no code execution is implied.
6. **Activated** — a reviewed runtime adapter is enabled under restricted permissions.
7. **Healthy** — real health checks pass; registration alone is not health.
8. **Suspended / revoked** — new work is denied; active work is safely cancelled or reconciled.
9. **Removed** — credentials and grants are revoked, data-retention/deletion obligations completed, and audit history retained as required.

Approval is not activation. Staging is not execution. A health URL in a manifest must not be fetched blindly. Artifact URLs and manifest data are untrusted input and must not create SSRF or path traversal paths.

## 6. Memory and context sharing rules

SPARK is a permissioned service, not a shared prompt dump.

Each memory record must eventually include:
- Memory ID, tenant, application and subject owner.
- Type: working, episodic, semantic, procedural, goal/project or explicit boundary.
- Source/provenance and capture method.
- Confidence and whether user-confirmed or inferred.
- Sensitivity/data classification.
- Created, updated, reviewed and expiry timestamps.
- Retention rule and deletion state.
- Access scope and authorized purpose.
- Correction and deletion lineage.

Memory retrieval must apply authorization before relevance ranking. Ranking cannot make an unauthorized memory eligible.

Cross-app memory sharing requires an explicit grant with:
- Source app and destination app/agent.
- Exact memory categories/fields.
- Stated purpose and expiry.
- User consent or another documented lawful authority.
- Revocation path and deletion propagation.
- Audit trail of access.

Sensitive personal data must not be inferred for personalization. Temporary moods and conversational hypotheses are not durable profile facts. Derived indexes, caches, summaries and embeddings must be included in correction and deletion workflows.

## 7. Agent coordination and authority

- BUD is the user-facing coordinator and explains what it is delegating.
- ORACLE handles reasoning and technical analysis.
- SPARK controls memory access and lifecycle; it does not silently persist every observation.
- ORBITS handles visual tasks only when the user or application has authorized the relevant image/file input.
- CONCIERGE coordinates practical service workflows. It may research options and prepare actions, but booking, purchasing, payments, sending messages or changing external records require a configured integration, app-scoped authorization and any required user confirmation. It must report only provider-confirmed outcomes.
- Agents receive scoped task envelopes, not shared database credentials.
- Agent-to-agent messages are untrusted inputs and carry task ID, actor, scope, purpose, deadline and permitted outputs.
- Agents cannot grant themselves capabilities, change tenant context, approve their own tools or override product policy.
- High-impact or external actions require a separate policy decision and, where required, explicit user/operator confirmation.
- Use durable task IDs, idempotency keys, checkpoints, cancellation, bounded retries, lease ownership and dead-letter handling.
- Treat outbox delivery as at-least-once unless a stronger guarantee is actually implemented; consumers must deduplicate.

## 8. Model gateway and privacy routing

The provider-neutral gateway must normalize:
- Text, structured output, streaming and tool-call contracts.
- Provider/model identity and version.
- Token usage, cost, latency and errors.
- Cancellation, deadlines, retry and circuit-breaker behaviour.
- Capability declarations and conformance evidence.

Routing decisions should consider task requirements, provider availability, privacy classification, data residency, contractual restrictions, cost budgets, latency and quality evidence.

Default routing:
- Restricted/private context: approved local or explicitly trusted private deployment only.
- Confidential context: only providers approved for that tenant/app and purpose.
- Public context: broader provider options only when the app's policy permits.

Do not infer that HTTPS alone makes a provider trustworthy. Record the route decision and reason. Never send secrets, credentials or unnecessary memory to a model. Model outputs are not verified facts or authorization decisions.

## 9. Product policy boundaries

UNIBUD, WAYWARD, SOULYNC and future apps may have different audiences and obligations. Oracle Arc must not flatten them into one universal policy.

Each app remains responsible for:
- Age eligibility and assurance where required.
- Consent, communication and relationship permissions.
- Content moderation, reporting, blocking and appeals.
- Academic record authority and official-source distinction.
- Financial authorization, regulated activity and provider requirements.
- Marketplace eligibility, prohibited goods/services and dispute handling.
- Jurisdiction, retention, privacy notices and user rights.

Oracle Arc may assist with explanation, classification or workflow execution, but must not be the sole enforcement mechanism for any of these areas. A tool must receive only the narrow app-scoped authorization necessary for its action.

## 10. Observability, evaluation and operations

Every request/task should be traceable with privacy-minimized metadata:
- Tenant/app/environment and credential identity.
- Request/correlation/task IDs.
- Agent, provider and model version.
- Policy version and capability grant IDs.
- Route reason, latency, usage/cost and outcome.
- Tool manifest/version/digest, approval reference and execution result.
- Retry, cancellation, idempotency and failure code.

Do not place raw private prompts, memory contents, access tokens or tool arguments in ordinary logs. Restricted diagnostic capture, if ever needed, must be explicitly controlled, minimized, access-audited and retention-limited.

Evaluation must include:
- Deterministic API, schema, authorization and isolation tests.
- Provider contract and failure-mode tests.
- Agent routing and delegation tests.
- Human-understanding scenario tests and blinded ratings.
- Memory provenance, scope, conflict, expiry and deletion tests.
- Sandbox escape, resource exhaustion, replay and approval-binding tests.
- Cross-app adversarial tests.
- Live provider/device tests clearly separated from mocked CI tests.

A critical security or privacy failure cannot be averaged away by a high quality score.

## 11. Delivery tracker — evidence-backed starting point

This table records what was visible in the repository branches at the time of writing. It is not a claim that the full platform is deployed.

| Workstream | Observed repository evidence | Status | Next gate |
|---|---|---|---|
| Personal single-owner API | PR #1 branch contains FastAPI owner-authenticated endpoints and SQLite store | Implemented on draft branch; deployment not verified | Preserve compatibility while designing consumer auth |
| Provider gateway | PR #1 contains `core/model_gateway.py`, Ollama adapter and capability manifest | Implemented on draft branch; live inference not verified | Reconcile with provider registry/fallback work on PR #2 |
| Human-understanding policy | PR #2 contains `core/human_understanding.py` and profile/boundary tests | Implemented on draft branch; live behaviour not independently evaluated | Add blinded behavioural evaluation |
| Agent registry | PR #2 contains `core/agent_registry.py` and worker/registry tests | Implemented on draft branch; enabled specialist runtime not fully proven | Verify connector wiring, authorization and independent worker operation |
| Task queue / outbox | PR #2 architecture describes leases, transactional outbox and SQLite single-host coordination | Partial; distributed deployment not present | Test crash recovery, cancellation, deduplication and shared-store constraints |
| Plugin isolation | PR #2 architecture documents rootless Podman worker and disabled arbitrary imports | Architecture/source claims require CI and host verification | Inspect worker code, build image, run adversarial isolation tests |
| Integration manager | PR #2 contains signed manifest review, digest approval and inert staging lifecycle | Partial; activation deliberately blocked pending runtime adapters | Keep activation blocked until per-integration adapter and sandbox review |
| SPARK memory governance | Existing architecture identifies owner-managed SQLite memory; master doc records missing provenance/sensitivity/expiry and scoped grants | Partial; not safe for autonomous cross-app memory | Design typed memory schema and tenant/app scoping before enabling |
| Multi-tenant / multi-app identity | Existing personal core is single-owner; no verified tenant isolation evidence in inspected core branch | Missing as an implemented capability | Build identity, credentials, tenant/app scoping and negative isolation tests |
| ORBITS visual runtime | Master architecture lists role but keeps ORBITS disabled pending runtime/tests | Not enabled / not verified | Define authorized media input contract, storage, processing and retention |
| App integrations | PR #2 has metadata/approval/staging mechanisms; no end-to-end consuming-app integration verified | Partial foundation; no live app integration claimed | Build first integration against a non-production test consumer |
| Production readiness | No live Ollama, production gateway, multi-worker deployment or production certification verified | Not production-ready | Complete all release gates and operational review |

### Branch reconciliation warning

At inspection time:
- PR #1: `feat/oracle-arc-personal-core`.
- PR #2: `feat/human-understanding-adaptive-intelligence`.
- Both branches diverge from a common ancestor. The comparison reported 51 commits unique to PR #1 and 227 commits unique to PR #2 after their merge base.
- The PR #2 branch contains substantial additional architecture and service work, while PR #1 contains later provider-gateway and security-audit changes.
- These branches must not be blindly merged or treated as interchangeable. In particular, `api.py`, `core/store.py`, `core/agent.py`, `core/plugins.py`, requirements and CI workflow have overlapping changes.
- The safe path is a deliberate integration branch: compare exact file histories, retain security fixes from both tracks, consolidate one canonical API/store/gateway/agent contract, then run the complete suite and migration checks.
- This document branch is based on PR #2's human-understanding branch only to preserve that work while adding the network-level architecture. It does not merge either draft PR.

## 12. Prioritized engineering sequence

### P0 — Establish one secure canonical foundation
1. Reconcile PR #1 and PR #2 into a dedicated integration branch; do not merge either draft PR as-is.
2. Audit current code for tenant/app identity propagation, auth boundaries, storage queries, logs, files, task queues and tool execution.
3. Introduce a server-authenticated request context and app-specific service credentials without exposing owner credentials.
4. Bind every persisted record and operation to explicit owner, tenant and app scope; add cross-tenant negative tests.
5. Preserve fail-closed provider routing and reconcile provider gateway contracts.
6. Verify plugin worker isolation on a real supported host; keep arbitrary plugin execution disabled until evidence passes.
7. Add approval binding to immutable tool/integration digests, exact action scope, expiry and replay protection.

### P1 — Make the shared platform operationally coherent
1. Define versioned application integration contract and registration lifecycle.
2. Add typed memory provenance, sensitivity, retention, grants and deletion propagation.
3. Add task checkpoints, cancellation, idempotency and outbox reconciliation.
4. Establish observability, credential rotation, backups, migrations and restore testing.
5. Add provider contract conformance, privacy-routing tests and usage budgets.

### P2 — Integrate real MY REALM consumers safely
1. Select one non-production consumer and prove the full authentication-to-response lifecycle.
2. Integrate BUD/ORACLE with a real consumer while preserving product-specific policy enforcement.
3. Add app-specific SPARK memory grants only after tenant isolation and deletion tests pass.
4. Add ORBITS only after authorized media handling, provider capabilities and retention are verified.
5. Expand to other apps one contract at a time; never enable all integrations by default.

### P3 — Quality, scale and refinement
1. Run blinded human-understanding and reasoning evaluations.
2. Add multi-worker/shared-database deployment only after concurrency and failure tests.
3. Add localization, accessibility, cost/latency optimization and service-level objectives.
4. Run independent security review and incident-response exercises.

## 13. Definition of done

A capability is not complete because code exists or a unit test passes. It is complete only when:
- The intended user/application journey works end to end.
- Authentication, tenant/app scope and authorization are enforced server-side.
- Cross-tenant and cross-app access is denied by adversarial tests.
- Data ownership, provenance, retention, correction and deletion work.
- Retries, duplicate delivery, cancellation and partial failures are safe.
- Logs and telemetry do not leak private context or credentials.
- Provider, agent and tool behaviour is verified under outage and malformed-input conditions.
- CI passes on the exact candidate commit.
- Live tests are recorded separately from mocked tests.
- Rollback, revocation, backup and restore paths are tested.
- Product owner approval exists for any production exposure or consequential capability.

## 14. Immediate next implementation task

The next code task after this architecture amendment is a **branch reconciliation and security gap audit**, not an immediate multi-tenant schema migration:

1. Fetch exact PR #1 and PR #2 heads and their CI run/job results.
2. Compare the overlapping API, store, gateway, agent, plugin, dependency and workflow files.
3. Identify security fixes present in only one branch.
4. Build a file-by-file merge plan and a canonical target interface.
5. Create a clean integration branch and port changes in small, testable commits.
6. Add tenant/app isolation only after the canonical API and persistence model are stable.

No PR is merged, no production data is migrated, no production service is deployed, and no restricted capability is activated by this document.
