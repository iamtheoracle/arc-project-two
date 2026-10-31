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

## Remaining high-priority work

| Priority | Work | State |
|---|---|---|
| P0 | Verify CI on this exact branch head | Pending |
| P0 | Restore personal-core request-body, rate-limit and concurrency protections without trusting spoofable proxy headers | Implemented; CI pending; ingress multi-worker controls still required |
| P0 | Reconcile `ArcAgent(host=...)` with a gateway-backed `LocalLLM` contract | Pending |
| P0 | Consolidate `core/model_gateway.py` and `core/providers.py` behind one provider contract | Pending |
| P0 | Add migration tests from both existing database shapes, including legacy name-only tool approvals | Pending |
| P0 | Preserve sandbox restrictions and fingerprint approvals through final reconciliation | In progress |
| P0 | Design tenant/app identities, scoped credentials and per-record ownership before any consumer app exposure | Not started |
| P1 | Add per-request privacy routing and provider allowlists, replacing the temporary global remote flag | Pending |
| P1 | Test queue/outbox recovery, backup semantics, idempotency and cancellation under failure | Pending |
| P1 | Add app-scoped memory grants, provenance, retention and deletion propagation | Not started |
| P2 | First non-production MY REALM consumer integration with explicit contract and tests | Not started |

## Important status boundary

This branch contains architecture documentation and focused security hardening. It is not yet the unified core, not multi-tenant, not approved for application consumers, and not production-ready. No merge, production migration, deployment or activation of integrations has occurred.
