# Oracle Arc Engineering Progress — 2026-10-31

**Working branch:** `feat/oracle-arc-network-platform-architecture`  
**Repository:** `iamtheoracle/arc-project-two`  
**Latest recorded commit:** `00c447a45996b6f02af5641a1be594e09a97e65f`  
**State:** Active development; not merged or deployed.

## Completed in this working branch

### 1. MY REALM network architecture
- Added `docs/ORACLE_ARC_NETWORK_PLATFORM_ARCHITECTURE.md`.
- Defines Oracle Arc as shared intelligence infrastructure for multiple MY REALM applications.
- Establishes tenant/application isolation, application-scoped credentials, agent roles, memory grants, product-policy boundaries, integration lifecycle, observability and release gates.
- Records the safe next sequence and makes clear that this is additive to prior work.

### 2. Branch reconciliation evidence
- Added `docs/ORACLE_ARC_BRANCH_RECONCILIATION_AUDIT_2026-10-31.md`.
- Records exact divergence and CI evidence for the two existing branches.
- Identifies provider fallback privacy, fingerprint-bound approvals, API resource guards, gateway signature compatibility, duplicate provider systems and missing tenant/app isolation.
- Specifies file-by-file ownership and safe reconciliation order.

### 3. Remote provider fallback now fails closed by default
- In `api.py::_build_agent_registry`, provider credentials alone no longer register remote connectors.
- Remote connectors require explicit server-side `ORACLE_ARC_ENABLE_REMOTE_PROVIDER_FALLBACK=true`.
- Reason: remote connectors receive system prompt context that can contain owner memories and conversation history.
- Added tests for default-off behaviour even when remote provider credentials exist, and for explicit operator opt-in.
- This is an interim global gate. It is not the final per-request, per-tenant or per-application privacy policy.

### 4. Tool approvals are now fingerprint-bound on the working branch
- `core/plugins.py` computes a SHA-256 digest from trusted built-in plugin source and canonical tool schema.
- `core/store.py` adds a nullable fingerprint column using an additive migration.
- Old approvals without a fingerprint fail closed and are not considered approved.
- Approval decisions bind the tool name to its current fingerprint.
- API runtime and approval routes compare the stored fingerprint with the current built-in registry fingerprint.
- Added tests for current digest acceptance, changed digest rejection, name-only fail-closed behaviour and malformed digest rejection.

### 5. CI branch coverage
- Updated `.github/workflows/verify.yml` so pushes to this working branch are included in the verification workflow.
- The prior personal-core CI run succeeded (run 41216114771).
- The prior human-understanding CI run succeeded, including real rootless Podman worker and sandbox restriction checks (run 41161023335).
- The working branch's own CI is **not yet verified**. Workflow runs 41248791535 and 41248756359 were observed queued on commit c78bfc2333e48fb7b12e01af3775e85df65d1434. New commits subsequently triggered further verification, which must be checked against the latest branch head. Do not treat queued runs or prior-branch CI as passing validation.

### 6. API request and inference resource guards added
- Added a bounded request-body middleware to the working branch. It rejects oversized declared and streamed bodies before endpoint processing.
- Added a process-local per-transport-peer sliding-window rate limiter with a bounded 10,000-key table. It deliberately ignores forwarded-IP headers; a trusted ingress must enforce limits across multiple workers.
- Added a bounded inference semaphore to reject excess chat work with HTTP 503 and Retry-After rather than allowing unbounded concurrent inference.
- Configuration is range-validated at startup; defaults are 1 MiB request bodies, 600 requests per source per minute, and one concurrent chat.
- Added API tests for streamed body rejection, spoofed forwarded-header handling, rate-limit responses and semaphore release.
- Commits: `ef2df1f18f839c5d462351a4eba825260b9402ed` (middleware/capacity), `63c9ca9f01b64f547e7a9b915cfb77e9fe97cc4e` (rate default), `00c447a45996b6f02af5641a1be594e09a97e65f` (tests).
- Important limitation: these in-process limits are not a substitute for gateway-level limits when multiple workers or replicas are deployed.

### 7. Canonical local-model gateway restored
- Restored the provider-neutral gateway and its capability/registry contract from the personal-core work without copying its incompatible facade verbatim.
- Updated `OllamaProvider` and `ModelGateway` to accept the per-agent host used by the adaptive agent registry.
- Updated `LocalLLM` to route all local model calls through the gateway while preserving the `ArcAgent(model=..., host=...)` constructor contract.
- Remote Ollama endpoints remain fail-closed unless explicitly allowed, and non-local Ollama requires HTTPS; no silent provider fallback is introduced.
- Restored gateway contract tests, including capability enforcement, malformed request rejection and facade routing.
- Commits: `cc4d688725e335b4abba0ca717d82a50d637cffd` (gateway), `ff8845fd6f18f4964976b8f95fbd43685ae7f39f` (facade), `38dd5d95e15c4284de7928938e6e403ddd33802e` (tests).
- Scope boundary: remote HTTP adapters in `core/providers.py` still use the agent-registry connector contract. Full adapter unification, normalized cancellation/usage semantics and per-request privacy routing remain pending.

### 8. Fingerprint migration and persistence regression coverage repaired
- A repository-wide test review found an older persistence test still using the pre-fingerprint approval API. That test would fail after the security migration.
- Updated the persistence test to use the current registry fingerprint and verify approval survives reopening the database.
- Added a legacy-schema fixture with a name-only approved row; migration adds the nullable fingerprint column while the legacy approval remains unusable (fail-closed).
- Added a current fingerprint approval reopen test.
- Commit: `50583c0ad6ca589a5381da5e86d73414390aaf57`.
- These tests are committed but remain pending execution by GitHub Actions.
- Follow-up test review added a true chunked-body case without `Content-Length`, and extended the gateway facade test to verify per-agent Ollama host forwarding. Commits: `648b9155580f8327a0720f4456a3f5ac0c2387d5` and `03e9c3c5f635d5afd876ea235ccaa1cbedec317b`.

### 9. Concierge added as a first-class specialist
- Added stable registry identity `concierge` with explicit capabilities: `service_discovery`, `booking_research`, `appointment_planning`, `travel_coordination` and `workflow_follow_through`.
- Concierge is registered but disabled by default until its runtime, integration contracts and authorization paths are implemented and tested.
- Its responsibility is practical coordination: discovering services, comparing options, researching booking/appointment choices, coordinating travel and tracking multi-step arrangements.
- It cannot claim a booking, purchase, payment, message or external change is complete without a configured integration and a provider-confirmed result. Product policies and explicit confirmations remain authoritative.
- Concierge receives only the minimum task-scoped location, schedule, contact or preference data. It does not get blanket SPARK memory access.
- Updated the master architecture, network architecture and registry tests.
- Commits: `f291d412a9577f59eaaaf3e0b15dcfb1801b1221` (registry), `ab88c8f51e350a0f1c026c8ad9a353ef3698c6e9` (tests), `0ea4d72b01f6660c102202278ce5b857ed2667d2` (master architecture), `b1f4cae38461b57f785f5870d299a425d7b2f7fe` (network architecture).

## Remaining high-priority work

| Priority | Work | State |
|---|---|---|
| P0 | Verify CI on this exact branch head | Pending |
| P0 | Restore personal-core request-body, rate-limit and concurrency protections without trusting spoofable proxy headers | Implemented; CI pending; ingress multi-worker controls still required |
| P0 | Reconcile `ArcAgent(host=...)` with a gateway-backed `LocalLLM` contract | Implemented; CI pending |
| P0 | Consolidate `core/model_gateway.py` and `core/providers.py` behind one provider contract | Partial: local Ollama gateway restored; remote adapter unification pending |
| P0 | Add migration tests from both existing database shapes, including legacy name-only tool approvals | Legacy name-only tool approval migration covered; full cross-branch schema matrix and rollback/backup tests pending |
| P0 | Preserve sandbox restrictions and fingerprint approvals through final reconciliation | In progress |
| P0 | Design tenant/app identities, scoped credentials and per-record ownership before any consumer app exposure | Not started |
| P1 | Add per-request privacy routing and provider allowlists, replacing the temporary global remote flag | Pending |
| P1 | Test queue/outbox recovery, backup semantics, idempotency and cancellation under failure | Pending |
| P1 | Add app-scoped memory grants, provenance, retention and deletion propagation | Not started |
| P1 | Implement Concierge runtime, approved service connectors, user-confirmed actions and provider-confirmed receipts | Registered and specified; runtime disabled/pending |
| P2 | First non-production MY REALM consumer integration with explicit contract and tests | Not started |

## Important status boundary

This branch contains architecture documentation and focused security hardening. It is not yet the unified core, not multi-tenant, not approved for application consumers, and not production-ready. No merge, production migration, deployment or activation of integrations has occurred.


## 10. Tenant and application isolation contract
- Added `docs/ORACLE_ARC_TENANT_ISOLATION_ENGINEERING_CONTRACT.md`.
- Establishes trusted request identity, tenant/app/principal scoping, additive migration requirements, memory-sharing grants, provider egress policy, agent capability checks, async task re-authorization, and mandatory adversarial acceptance tests.
- Explicitly records the current system as a private single-owner API/store; this document does not claim tenant isolation is implemented.
- Multi-tenant/customer-facing access remains blocked until migration, enforcement, cross-scope tests, operational controls and controlled-pilot gates are complete.
- Commit: `1f31d60140fc8c77271e07d39ed191792a552255`.


## 11. First tenant-scoped application access vertical slice

**Implemented in code on this branch; not yet production-verified.**

- Added `core/tenant_security.py` with additive control-plane tables for tenants, applications, principals, hashed/revocable application credentials, app-scoped SPARK memories, explicit memory-sharing grants, and tenant/app/principal-scoped agent tasks.
- Added `core/platform_routes.py` and mounted it under `/v1/platform` in `api.py`.
- Owner-only control-plane endpoints provision tenants/apps, issue one-time application credentials, and revoke credentials.
- Application credentials resolve tenant, application, principal, capability set and policy version from server-side database state. Request bodies and headers cannot choose the identity scope.
- Scoped SPARK memory endpoints enforce application/principal boundaries, separate sensitive-memory capability, and explicit purpose/category/expiry-bound sharing grants with revocation.
- Scoped agent task endpoints persist scope, check agent dispatch plus requested capabilities at enqueue, re-check scope/capabilities at claim and completion, and hide cross-app task IDs.
- Legacy owner routes remain owner-only; app credentials do not authenticate to those legacy endpoints. Existing owner data is not automatically migrated into new tenants.
- Additive SQLite tables are initialized lazily by the platform router. A production migration/backup/restore procedure and cross-database deployment plan remain required.
- Added API and unit tests for credential revocation, app isolation, memory sharing/revocation, sensitive-memory gating, task isolation and cross-app denial. CI status pending.

## 12. Privacy-aware provider gateway

- Added `core/privacy_aware_gateway.py` with a single provider decision interface, request-scoped tenant/app/principal policy, data classification, provider allowlist and region checks.
- Remote model providers require explicit per-request policy; credentials or environment variables alone do not authorize data export.
- Remotely hosted Ollama is treated as remote egress and requires explicit allowlisting. Local Ollama remains available without remote egress permission.
- Existing agent registry no longer attaches remote provider connectors based on the former global `ORACLE_ARC_ENABLE_REMOTE_PROVIDER_FALLBACK` flag. This is intentionally fail-closed until all app-agent inference calls pass a trusted `InferencePolicy`.
- The privacy-aware gateway module is implemented, but complete migration of all existing agent inference calls to this gateway remains pending. Do not claim unified production routing yet.

## 13. CONCIERGE confirmation-gated workflow runtime

- Added `core/concierge_runtime.py` with tenant/app/principal-scoped workflow records, canonical action fingerprints, expiry, atomic one-time confirmation claim, and provider receipt requirement.
- Added platform routes for planning and confirming actions. Planning does not execute. Execution requires `concierge.action.execute`, exact action fingerprint confirmation and a server-registered provider executor.
- No provider executor is registered by default; consequential actions return a fail-closed unavailable response. No booking, payment, message, purchase or external change is activated.
- Added tests for wrong-fingerprint rejection, cross-app workflow denial and provider-confirmed receipt requirement.

## 14. Remaining integration gates

- Integrate the privacy-aware gateway into every app-scoped agent inference call, including context construction that uses only the current app's authorized SPARK memories.
- Route scoped task claims through a separately authenticated worker service identity and re-authorize grants/credential revocation at execution time; current queue methods intentionally constrain worker operations to the originating principal context.
- Add scoped agent runtime wiring. The new scoped task queue does not yet authorize the legacy owner agent registry to read app data.
- Add credential rotation, tenant/app suspension APIs, audit log redaction, rate limiting by credential/tenant and operational key management.
- Add migrations/backups/restore drills for production DBs, concurrent migration tests and adversarial cross-tenant tests on a production-like database.
- Add a reviewed CONCIERGE provider adapter for each allowed action type, idempotency handling, provider receipt verification and recovery for workflows left in executing state.
- Run CI and fix all failures before treating this vertical slice as verified.
