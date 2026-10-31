# Oracle Arc Tenant and Application Isolation — Engineering Contract

**Status:** Required precondition for any multi-application or customer-facing deployment  
**Scope:** Oracle Arc shared intelligence infrastructure for MY REALM applications  
**Current implementation:** Private single-owner API and shared owner store; this document is a design and acceptance contract, not a claim that tenant isolation is implemented.

## 1. Non-negotiable security invariants

1. Every authenticated request resolves to one immutable server-verified principal, tenant, and application context.
2. A client-supplied tenant ID, app ID, user ID, role, memory scope, or capability is never authoritative.
3. Every tenant-owned database read, update, delete, list, task claim, outbox operation, audit event, and cache lookup is scoped by tenant and application. User-owned data is additionally scoped by principal.
4. Cross-application access is denied by default, including between two apps belonging to the same tenant.
5. Cross-application memory sharing requires a separately stored, explicit, revocable grant naming the source app, destination app, data categories, purpose, expiry, and grant version.
6. Revocation takes effect on the next authorization decision; cached grants must be versioned or invalidated.
7. Agent identity is not authorization. BUD, ORACLE, SPARK, ORBITS, and CONCIERGE receive only capabilities explicitly granted for the current task.
8. Provider credentials do not authorize data egress. Remote inference requires a policy decision over tenant, app, data classification, provider, region, and purpose.
9. Background tasks and outbox events carry immutable tenant/app/principal context and re-authorize before performing sensitive work.
10. Logs and traces must not contain raw prompts, memory contents, access tokens, provider secrets, or unnecessary personal data.

## 2. Identity and request context

Resolve authentication in this order:

1. Validate the credential using a constant-time comparison or a trusted identity-provider verifier.
2. Resolve credential status, expiry, rotation version, and revocation.
3. Resolve the credential's server-side tenant and application assignments.
4. Resolve the principal and current role/entitlements.
5. Build an immutable request context:
   - `request_id`
   - `credential_id`
   - `tenant_id`
   - `application_id`
   - `principal_id`
   - `roles`
   - `capability_grants`
   - `policy_version`
   - `issued_at`
6. Reject missing, ambiguous, disabled, expired, revoked, or mismatched assignments before loading conversation or memory data.

The existing owner bearer key remains a private owner/admin credential. It must not silently become a customer or application credential.

## 3. Data model and migration strategy

Use additive migrations first. Do not rewrite or reinterpret existing owner records in place.

### Core control-plane tables

- `tenants`: tenant identity, status, created/updated timestamps.
- `applications`: application identity, tenant foreign key, registered product name, status, policy version.
- `principals`: principal identity and status.
- `credentials`: hashed credential verifier, credential ID, tenant/app binding, scopes, expiry, rotation version, revoked timestamp. Never store bearer secrets.
- `tenant_memberships`: principal-to-tenant relationship and role.
- `application_memberships`: principal-to-app relationship and app-specific role.
- `capability_grants`: subject, tenant, app, capability, resource scope, purpose, expiry, grant version, revoked timestamp.
- `memory_sharing_grants`: source app, destination app, owner/principal, allowed categories, purpose, expiry, version, revoked timestamp.

### Tenant-owned data tables

Add non-null `tenant_id` and `application_id` to conversations, messages (directly or via enforced parent scope), memories, tool permissions, tasks, outbox events, integration approvals, audit events, and any future user profile or preference tables. Add `principal_id` where ownership is user-specific.

Required database protections:

- Composite uniqueness and indexes include tenant/app scope where appropriate.
- Foreign keys prevent a child row from referencing a parent in another tenant/app.
- Queries use explicit scope predicates; do not rely on filtering after retrieval.
- SQLite deployments must enable foreign keys on every connection (the current store already does this).
- For PostgreSQL, use row-level security as defense in depth, while retaining explicit application-level scope predicates.
- Never use a global in-memory cache keyed only by conversation ID, task ID, user ID, or tool name.

### Existing owner data

1. Take and verify a restorable backup.
2. Create a dedicated legacy-owner tenant and owner application.
3. Backfill existing records only into that isolated owner scope.
4. Verify row counts, foreign keys, and checksums.
5. Run cross-scope negative tests against the migrated copy.
6. Keep rollback instructions and a migration ledger.
7. Do not expose tenant endpoints until migration verification succeeds.

## 4. Authorization contract

Authorization must be deny-by-default and evaluated at the point of use. A successful login does not imply access to every resource.

For every operation, check:

- authenticated principal is active;
- tenant and application are active and bound to the credential;
- principal has membership or an explicit service identity grant;
- requested capability is granted for this application and resource;
- resource tenant/app/principal scope matches the request context;
- purpose and data classification are permitted;
- grant has not expired or been revoked.

Use one policy decision interface for HTTP handlers, agent dispatch, background workers, plugins, memory access, and integration actions. Avoid duplicated ad-hoc permission checks.

## 5. SPARK memory contract

Memory retrieval must accept a trusted request context and an explicit scope. The default query is restricted to the current principal + tenant + application.

Memory categories should be independently controllable (for example: preferences, active projects, learning context, sensitive context). Sensitive categories require a separate explicit grant and may be excluded from remote-provider prompts.

Memory operations must support access, correction, export, deletion, retention expiry, and deletion audit records. Deletion must cascade or tombstone dependent embeddings, summaries, caches, and derived indexes. A deleted memory must not reappear from a stale backup or retrieval index.

## 6. Provider and agent execution contract

Before dispatch:

1. Resolve the target agent and declared task capabilities.
2. Authorize those capabilities for the current tenant/app/principal.
3. Classify the prompt and attached context.
4. Evaluate the selected provider against app policy, data classification, region, and explicit egress permission.
5. Build the minimum context required for the task.
6. Record a redacted decision event with policy version and provider identity.

ORACLE does not gain unrestricted memory access by being the reasoning specialist. SPARK is a permissioned memory service, not a global context dump. ORBITS receives only assets explicitly supplied or authorized. CONCIERGE must re-check authorization before each external action and require user confirmation for consequential actions. Provider failure must not silently route private context to another provider.

## 7. Async tasks, retries, and idempotency

Every task and outbox event must persist tenant/app/principal, originating request ID, policy version, requested capability set, and idempotency key. Worker claims must be atomic and tenant-scoped. Re-authorize before execution and before external side effects. A retry must not repeat a payment, booking, message, or other consequential action; use provider idempotency keys and persist provider-confirmed receipts.

## 8. Mandatory acceptance tests

Do not enable multi-tenant access until automated tests prove all of the following:

- App A cannot read, list, update, delete, infer, or enumerate App B conversations, messages, memories, profiles, tool approvals, tasks, events, or integrations.
- Tenant A cannot access any resource in Tenant B, even when IDs are guessed or deliberately reused.
- A principal removed from an app loses access immediately, including through an existing session.
- Revoked, expired, rotated, or disabled credentials fail closed.
- Forged tenant/app/principal headers and request-body fields cannot change resolved context.
- Agent delegation cannot elevate capabilities or change tenant/app context.
- A memory-sharing grant exposes only allowed categories, only to the destination app, and stops working immediately after revocation.
- Background jobs cannot run after membership, credential, or capability revocation.
- Provider fallback cannot transmit data when egress is denied; retries cannot widen the provider allowlist.
- Cache keys, search indexes, embeddings, audit views, and exports preserve scope.
- Migration from the current owner-only database preserves owner data without granting access to any new tenant.
- Backup restore and deletion/retention tests preserve the same isolation guarantees.

## 9. Rollout gates

**Gate A — Design:** schema, request context, policy contract and threat model reviewed.

**Gate B — Migration:** additive migrations, verified backup/restore, owner-data backfill and rollback tested on copies.

**Gate C — Enforcement:** every API and worker path uses the same trusted request context and authorization interface.

**Gate D — Adversarial tests:** all negative cross-tenant and cross-app tests pass, including concurrent and async paths.

**Gate E — Operational controls:** ingress rate limits, secret rotation, audit monitoring, incident response, retention and restore drills are in place.

**Gate F — Controlled pilot:** explicit approval, isolated test tenants, no real consequential actions, and monitored rollout.

Until all gates are complete, keep the API private and single-owner. Do not advertise or expose the current owner-only store as a multi-tenant platform.
