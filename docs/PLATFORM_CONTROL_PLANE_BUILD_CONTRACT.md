# Oracle Arc Platform Control Plane — Build Contract and Hardening Plan

**Repository:** `iamtheoracle/arc-project-two`  
**Working base:** `feat/oracle-arc-network-platform-architecture`  
**Purpose:** Evolve the existing Oracle Arc service into a reliable, tenant-isolated intelligence platform.  
**Status:** Engineering plan grounded in the current repository; not a claim that every planned capability is complete.

## 1. Product and architecture intent

Oracle Arc is the shared intelligence core for the Oracle-Arc ecosystem. It is a standalone service, not a UNIBUD, Vantoris X Money, Arc Space or My Realm business application.

The intended specialist roles are:
- **BUD — coordinator and everyday companion:** understands the request, keeps the user oriented and coordinates specialist work.
- **ORACLE — reasoning and problem-solving:** deep analysis, research, engineering, planning and structured decisions.
- **SPARK — permissioned memory and continuity:** stores, retrieves, updates and governs user-approved memory.
- **ORBITS — visual intelligence and creative workflows:** image understanding, visual analysis, diagrams and creative production.

These are distinct agent identities and responsibilities over a shared Arc platform. They must not become four copies of the same unrestricted assistant. A specialist may only use capabilities, memory categories, tools, model routes and data scopes explicitly granted to it.

## 2. Platform control-plane responsibilities

The control plane is responsible for registering and governing applications, agents, model routes, permissions, quotas and executions. It is not itself an arbitrary code loader and must never execute an untrusted manifest or uploaded artifact.

The required lifecycle is:

1. Owner provisions a tenant and an application.
2. Application receives a revocable, expiring credential bound to tenant, application, principal and explicit capabilities.
3. Application registers an immutable agent version with a validated manifest.
4. The agent version declares required capabilities, allowed tools and permitted model routes.
5. An authorised model route resolves provider/model only when its data classification and region policy match.
6. A scoped execution is submitted with a bounded payload and idempotency key.
7. Quota and concurrency policy are enforced atomically before accepting work.
8. A trusted worker claims the execution with a lease and worker identity.
9. The worker revalidates the live agent version, application credential/scope, route policy and tool grants before execution.
10. The worker executes through a provider adapter and a least-privilege tool broker.
11. Completion, failure, cancellation, retry and dead-letter transitions are persisted atomically.
12. Usage is recorded against the correct tenant, application, execution and metric.
13. The application can read only its own execution status/result and usage.
14. Owner/operator controls can revoke credentials, disable agent versions/routes, pause workloads and inspect safe audit metadata.

A queued execution must not become an implicit grant to execute arbitrary code or perform consequential external actions.

## 3. Existing repository foundations observed

The following were found on `feat/oracle-arc-network-platform-architecture` during this review:

- `api.py`: owner-authenticated personal API, local Ollama inference, provider and agent wiring, request guards, task endpoints and platform router mounting.
- `core/platform_routes.py`: application credential identity, tenant/application provisioning, scoped memory, memory-sharing grants, scoped task endpoints, Concierge workflow confirmation and control-plane HTTP endpoints.
- `core/tenant_security.py`: tenant/application credentials and scoped memory/task data layer.
- `core/tenant_identity.py`: application credential identity model.
- `core/platform_control_plane.py`: SQLite-backed agent-version manifests, model routes, quota configuration, execution queue/lifecycle, usage ledger and tenant/application scoping.
- `core/agent_registry.py`: trusted in-process connector registry and session connector registry; not an arbitrary plugin importer.
- `core/agent_worker.py`: independent worker entry point for the earlier task queue.
- `core/implementation_planner.py`: deterministic capability recommendations; not an autonomous model planner.
- `tests/test_platform_control_plane.py`: tests for immutable agent versions, application isolation, model classification/region, quota, idempotency, usage, lease recovery and visibility boundaries.
- `tests/test_api.py`: broad API tests for authentication, task queue, outbox, agent routing, integration approval and other safety gates.

This inventory is a code inspection, not a claim that production deployment, multi-host operation or live Ollama inference has been verified.

## 4. Critical architectural distinction: two task systems

The repository currently contains two different task/execution paths:

1. The personal owner-only agent task queue in `ArcStore`, used by `/v1/agents/{agent_id}/chat` and `/v1/agent-tasks/*`.
2. The tenant/application-scoped platform execution queue in `PlatformControlPlane`, exposed through `/v1/platform/executions`.

Do not assume these are already one connected runtime. The next implementation must explicitly define how a platform execution is claimed by a trusted worker, resolved to the registered agent version and model route, dispatched to the correct provider, and completed with usage and audit records. Do not silently route application work through the personal owner-only task queue or expose personal memory to application tenants.

## 5. Highest-priority engineering gaps to verify and close

### P0 — execution lifecycle and isolation

- Verify the full platform execution path. The inspected platform routes expose submit/read/cancel/usage operations, but the worker dispatch/claim/heartbeat/recovery path must be traced end to end. Implement missing platform worker operations rather than assuming the personal task worker covers them.
- Worker identity must not be a caller-chosen string that any ordinary application credential can impersonate. Introduce a separate worker authentication mechanism with worker IDs, scoped capabilities, credential rotation/revocation and least-privilege queue assignment.
- A worker must not be able to claim or complete another tenant/application's task by changing an ID, worker name or request payload.
- Recheck credential revocation, application status, agent version status, model-route status and policy immediately before execution, not only at submission.
- Cancellation must prevent a late worker result from overwriting a cancelled execution. Define cooperative cancellation and provider timeout semantics.
- Lease renewal and completion must be atomic and conditional on the current lease owner and unexpired lease. Expired workers must not complete or publish results.
- Retries must be bounded, backoff-aware and idempotent. Distinguish retryable provider failures from permanent policy, validation and permission failures.
- Dead-letter records need safe operator inspection, replay controls and an audit trail. Replay must not bypass current policy.
- Ensure idempotency keys cannot return a prior execution for a different payload. Store and compare a canonical request digest, scope keys to tenant/application, and reject conflicting reuse.
- Validate that concurrent quota checks are transactionally safe under load. Define whether failed/cancelled executions consume the rate quota and how concurrent reservations are released.
- Usage events must be idempotent and tied to the execution's verified provider response. Prevent an application from fabricating arbitrary usage quantities or writing usage to another execution.

### P0 — model routing and data protection

- Resolve model provider and model ID from a trusted, enabled route; never trust provider/model supplied in execution payload.
- Enforce data classification and region on every attempt, including retries and fallback. A fallback provider must satisfy the same or stricter policy.
- A route change or disablement after queueing must be rechecked before execution.
- Remote providers must remain disabled unless the application has an explicit privacy policy and provider allowlist for the data classification. Credentials remain server-side.
- Avoid logging prompts, memories, images, tool arguments, credentials or sensitive outputs. Audit metadata should be sufficient to trace decisions without duplicating private content.

### P0 — agent manifests and scoped tools

- Treat registered agent versions as immutable. Any change creates a new version and digest.
- Validate exact manifest schema, version format, capabilities, tool IDs, route IDs, size bounds and canonical digest.
- The manifest cannot grant itself permissions. The application credential must already possess every required capability and tool grant.
- At execution time, intersect agent-declared tools, application grants, owner policy and tool broker allowlist. Never use a union.
- A tool call must be checked for agent version, tenant, application, principal, permission scope, argument schema, rate limit and consequential-action approval.
- Tool execution must occur in a reviewed sandbox with bounded CPU, memory, time, filesystem and network access. Unknown tools fail closed.
- Disabling an agent version must block new claims and prevent a stale worker from completing consequential work under a disabled version.

### P1 — operational platform controls

- Add owner/operator inventory for tenants, applications, credentials, agents, routes, active executions, workers, quota and dead letters.
- Add application suspend/resume and credential rotation/revocation workflows with immediate enforcement.
- Add per-application concurrency and rate metrics, queue latency, provider latency/error, retries, timeout, cancellation and dead-letter metrics.
- Define retention and deletion for execution payloads/results, audit records, usage and memory.
- Add health/readiness checks that distinguish API availability, database availability, worker availability, model provider health and configured route readiness.
- Add backup/restore and migration tests. SQLite is a single-host deployment boundary; multi-host workers require a shared transactional database such as PostgreSQL and an operationally tested migration path.
- Add deployment configuration validation so unsafe or contradictory settings fail at startup.

## 6. Required APIs and ownership model

The exact route names may follow established conventions, but the contract must include:

- Owner-only tenant and application lifecycle management.
- Owner-only credential issuance, rotation and revocation; secrets displayed once.
- Application-scoped agent version registration/read/disable.
- Application-scoped model route configure/read/disable.
- Application-scoped quota configure/read.
- Application-scoped execution submit/read/cancel.
- Worker-authenticated claim/heartbeat/complete/fail operations.
- Application-scoped usage read; worker/provider-verified usage write.
- Owner/operator platform status, safe audit and dead-letter inspection/replay.
- Explicit agent/tool permission grants and revocations.

Every endpoint must state the identity type it accepts and enforce tenant/application/principal scope server-side. Avoid caller-supplied scope IDs as authority.

## 7. Agent execution contract

A trusted worker should receive only a minimal, validated execution envelope:

- execution ID and idempotency/request digest;
- tenant/application/principal IDs from authenticated stored context;
- immutable agent ID/version/manifest digest;
- model route ID and resolved policy-approved provider/model;
- data classification and region;
- approved capability/tool set;
- bounded input payload or protected payload reference;
- lease ID/owner/expiry and attempt count;
- cancellation state and deadline.

The worker must not receive the owner's personal API key, raw provider secrets, unrestricted database access, or unrelated tenant data. Tool and model access should be mediated by narrow server-side adapters.

The result envelope should contain validated output, provider/model metadata, measured usage where available, safe error code, execution timing and trace/correlation IDs. Avoid persisting secrets or raw stack traces into tenant-visible records.

## 8. Test matrix — required before production claims

### Identity and isolation
- Tenant A cannot enumerate, read, cancel or record usage for Tenant B.
- Application A cannot read another application in the same tenant unless an explicit scoped grant exists.
- Revoked/expired credentials fail immediately.
- Caller-supplied tenant/application/principal IDs never override authenticated identity.
- Worker credentials cannot be used as application credentials and vice versa.

### Agent and tool policy
- Agent version cannot be overwritten.
- Agent cannot request capabilities/tools not granted to its application.
- Disabled agent version cannot be newly claimed or executed.
- Tool permission revocation blocks subsequent tool calls.
- Unknown or modified tool fingerprints fail closed.
- Manifest digest tampering is rejected.

### Model routing
- Classification mismatch and region mismatch are denied.
- Disabled or changed route is rechecked before execution.
- Remote fallback cannot receive data unless separately authorised.
- Provider/model fields supplied by client are ignored or rejected.

### Queue and lifecycle
- Concurrent workers cannot claim the same execution.
- Only the active lease owner can heartbeat or complete.
- Expired lease owner cannot complete.
- Cancellation wins against late completion.
- Retry attempts are bounded and backoff is applied.
- Dead-letter replay rechecks current identity, agent, route, tools and quota.
- Same idempotency key plus same digest returns the original execution.
- Same idempotency key plus different digest returns conflict.
- Duplicate completion/usage events do not duplicate results or ledger rows.

### Quotas and accounting
- Concurrent submissions cannot exceed configured concurrency/rate limits.
- Oversized payloads are rejected before queueing.
- Failed/cancelled execution quota accounting is deterministic and documented.
- Usage is linked to a valid execution and trusted source.
- Application cannot submit arbitrary usage values as if provider-confirmed.

### Operations
- Worker/API/database/provider outages produce clear health states.
- Restart recovers queued and expired-lease work safely.
- Backup/restore and migration rollback/recovery are tested.
- Logs contain no credentials, raw prompts or sensitive tool arguments.

## 9. Implementation sequence

1. **Inventory and contract:** trace the current platform routes, database schema, migrations, worker process, tests and deployment configuration. Record verified versus unverified behaviour.
2. **Worker trust boundary:** implement worker credentials and worker-scoped claim/heartbeat/complete APIs. Remove any authority based on caller-chosen worker IDs.
3. **Platform queue lifecycle:** connect platform executions to an independent worker runtime; implement leases, cancellation, retry, dead-letter and recovery.
4. **Execution dispatcher:** resolve immutable agent version, scoped tool grants and policy-compliant model route at claim/execute time.
5. **Usage and quotas:** make quota reservation and usage ledger idempotent and provider/worker verified.
6. **Operator controls:** application/credential/route/agent suspension, worker health and dead-letter review.
7. **Hardening and evidence:** adversarial multi-tenant tests, concurrency tests, live local Ollama smoke tests and deployment/recovery validation.

Keep each step in a small reviewable pull request. Do not merge, deploy, apply production migrations, activate external tools or enable consequential integrations without explicit owner approval.

## 10. Definition of done

The control plane is not complete merely because registration and submission endpoints return success. It is complete only when an isolated application can register a versioned agent, choose a policy-compliant route, submit a bounded idempotent task, have a separately authenticated worker execute it under scoped permissions, recover safely from worker/provider failures, cancel it without late writes, record trustworthy usage, and read only its own result — with adversarial tests proving the boundaries.

**Instruction to the Oracle Arc building AI:** Preserve the existing private owner-authenticated personal core. Build the multi-application platform beside it using explicit tenant/application/worker identities. Keep BUD, SPARK, ORACLE and ORBITS distinct. Connect their capabilities through contracts, not shared unrestricted access. Prove the complete execution lifecycle with tests before calling the platform operational.
