# Oracle Arc — Branch Reconciliation and Security Compatibility Audit

**Date:** 2026-10-31  
**Repository:** `iamtheoracle/arc-project-two`  
**Working branch:** `feat/oracle-arc-network-platform-architecture`  
**Scope:** Evidence-based comparison of the personal-core and human-understanding branches.  
**Status:** Audit and a first privacy hardening patch committed; full reconciliation is not complete.

## 1. Branch evidence

The two development branches diverged from merge base `5260896765ea788fa8726dc4090dd65e18a34d85`.

| Track | Branch | Commit at audit | Unique commits in comparison | CI evidence |
|---|---|---|---:|---|
| Personal core | `feat/oracle-arc-personal-core` | `b9eb9602f78b222eb9df4a04ec5da5b5a0780c83` | 51 | Run 41216114771, job 124580871647: completed success |
| Human understanding | `feat/human-understanding-adaptive-intelligence` | `88f0799a6a43352d7a8dbab5e08a251e51f230de` | 227 | Run 41161023335, job 124418384975: completed success; includes real rootless Podman worker and sandbox checks |
| Network architecture | `feat/oracle-arc-network-platform-architecture` | New working branch | Additive to human-understanding branch | New CI execution must be verified separately |

The compare API reports the branches as diverged. They are not a simple fast-forward relationship. Do not merge either PR directly into the other without a controlled reconciliation.

## 2. Confirmed compatibility and security gaps

### R-01 — Remote model fallback can receive private context

**Evidence:** On the human-understanding branch, `api.py::_build_agent_registry` registers OpenRouter, Groq and Gemini connectors whenever their server API keys exist. The remote connector builds messages using `_system_prompt(runtime_store, ...)` and conversation history. The system prompt may include owner-managed memory, profile preferences and boundaries.

**Risk:** Presence of a provider credential is not user consent or a privacy-routing decision. A remote fallback could transmit private context without a per-request privacy decision.

**Change already committed on the working branch:** Remote providers are now excluded unless the server operator explicitly sets `ORACLE_ARC_ENABLE_REMOTE_PROVIDER_FALLBACK=true`. Tests cover default-off behaviour even when provider keys exist and explicit opt-in. This is a temporary global fail-closed control, not the final per-tenant/per-application privacy policy. Remote routing must remain disabled for restricted context until request-level policy and provider approval exist.

### R-02 — Fingerprint-bound tool approvals are not preserved by the newer store/API

**Evidence:** The personal-core store adds a `fingerprint` column to `tool_permissions`; its `approved_tools(current_fingerprints)` only returns approvals whose stored digest matches the current tool implementation. Its API passes `PluginRegistry.tool_fingerprints` when loading approvals. The human-understanding store's `approved_tools()` selects only tool names, and `set_tool_approval(name, approved)` does not bind approval to code or schema digest.

**Risk:** A previously approved tool name may remain approved after its implementation or schema changes. The newer branch therefore regresses an important approval-binding safeguard.

**Required reconciliation:** Port digest-bound approvals into the newer store using a migration that adds the nullable fingerprint column without destroying existing records. Existing approvals without a fingerprint must become unapproved (fail closed). Generate stable digests from trusted built-in source plus canonical tool schema. All runtime paths must compare current digests; all approval routes must bind the exact current digest. Add tests for changed source, changed schema, unknown tool, revocation, and legacy rows.

### R-03 — Request resource protections from personal-core are absent in the newer API

**Evidence:** The personal-core API contains `RequestGuardMiddleware`, streamed request-body size enforcement, bounded per-client rate buckets, and a chat concurrency semaphore. These are not present in the human-understanding API's top-level setup.

**Risk:** A merge that keeps only the newer API drops protections against oversized request bodies, request floods and uncontrolled concurrent inference.

**Required reconciliation:** Port the protections as independently testable middleware/dependencies. Ensure rate limiting keys are derived from a trusted reverse-proxy configuration; do not blindly trust spoofable forwarded headers. Bound bucket memory and define multi-worker/distributed rate-limit behaviour. Keep request size enforcement for chunked bodies, not only Content-Length. Add concurrency tests and verify middleware doesn't break streaming or disconnect handling.

### R-04 — Agent host override and gateway facade signatures conflict

**Evidence:** Both agent implementations accept an optional `host` and construct `LocalLLM(model=model, host=host)`. The personal-core branch's new `core/llm.py` facade constructor accepts only `model` and `temperature`, and creates `ModelGateway()` without a host override. The human-understanding branch's legacy `core/llm.py` accepts `host` but bypasses the new provider-neutral gateway.

**Risk:** Naively copying the personal-core gateway facade into the newer branch causes a constructor mismatch for host-based Ollama failover. Keeping the old facade means the provider gateway is not the canonical path.

**Required reconciliation:** Define one canonical gateway contract with an explicit endpoint/host selection object. Preserve Ollama primary/backup routing without mutating global environment state. Make the agent depend on a provider interface, not directly on the Ollama SDK. Contract-test provider errors, timeout, cancellation, fallback, tool calls and streaming.

### R-05 — Two provider systems currently coexist

**Evidence:** Personal-core adds `core/model_gateway.py` with provider manifests and a fail-closed Ollama adapter. Human-understanding adds `core/providers.py` with fixed remote endpoints and its own `OpenAICompatibleProvider`, while its agent registry directly wires Ollama hosts and remote providers.

**Risk:** Duplicated provider configuration and inconsistent capability, privacy, error, usage and fallback semantics.

**Required reconciliation:** Keep one provider contract and adapter registry. Move the fixed remote endpoint adapters behind that contract. Route selection must be explicit and policy-aware; credentials must not automatically enable fallback. Preserve provider manifests and capability checks. Do not remove remote-provider support; make its use controlled and auditable.

### R-06 — Existing API contract is owner-only, not yet a multi-application platform

**Evidence:** Both branches use a single `ORACLE_ARC_API_KEY` and `require_owner`. Persistence tables for memories, conversations, profiles, tasks and permissions do not carry verified tenant/application ownership columns.

**Risk:** The code cannot yet safely serve multiple MY REALM applications or multiple users. Adding an app name to prompts or headers would not create tenant isolation.

**Required reconciliation:** Do not expose this API to consumer applications as-is. Design server-authenticated application credentials, subject identity, tenant/app scope, policy version and capability grants. Add ownership columns through versioned migrations and enforce them in every query and operation. Add cross-tenant and cross-app negative tests before any shared deployment.

### R-07 — CI coverage differs across branches

**Evidence:** The personal-core run completed its test job successfully. The human-understanding run completed tests and additional real rootless Podman image build, isolated worker execution and in-container restriction checks successfully. The human-understanding workflow's branch filters did not include the new network-architecture branch; the working branch adds it to push verification.

**Risk:** A green run on either source branch is not proof that the reconciled branch passes. A workflow that does not trigger on the working branch leaves changes unverified.

**Required reconciliation:** Verify the new branch's own workflow execution, inspect job steps and logs, and require the full suite plus real sandbox tests on the final integration candidate. Add pull-request trigger coverage for the chosen integration target when the PR is created.

## 3. File-level integration decisions

| File / area | Preserve from personal-core | Preserve from human-understanding | Canonical target |
|---|---|---|---|
| `api.py` | Request guard, request limits, concurrency controls, safe error responses | Agent routes, reasoning/human-understanding, durable tasks, integration lifecycle | One API with versioned auth and policy middleware |
| `core/llm.py` | Gateway compatibility facade | Agent interface compatibility only | Thin facade over one provider-neutral gateway |
| `core/model_gateway.py` | Provider protocol, manifests, capability validation, fail-closed routing | Fixed remote adapters and Ollama host fallback behaviour | Single provider adapter registry |
| `core/providers.py` | No duplicate routing authority | Fixed endpoint and credential handling, after adaptation | Provider adapters registered through gateway |
| `core/store.py` | Fingerprint-bound approvals | Profiles, boundaries, tasks, outbox, integration approvals, in-memory test support | One versioned store with additive migrations and scope ownership |
| `core/plugins.py` | Tool digest/approval model and strict validation | Fixed built-in allowlist and isolated Podman worker | Only reviewed built-ins and approved sandbox workers |
| `core/agent.py` | Host/gateway interface compatibility | Agent loop and BUD/ORACLE roles | Agent depends on canonical gateway and scoped tool executor |
| `.github/workflows/verify.yml` | Request/API regression checks | Real rootless Podman sandbox tests | One workflow covering every active candidate branch |

## 4. Safe implementation order

1. Keep the current working branch separate; do not merge PR #1 or PR #2.
2. Complete the remote-provider default-off tests and verify the branch CI.
3. Restore fingerprint-bound approvals in the newer store and API.
4. Restore request-size, rate and concurrency protections.
5. Reconcile the agent/gateway constructor contract and provider adapter duplication.
6. Compare migrations and run upgrade tests from both branch schemas, including pre-existing database files.
7. Only then design tenant/application identity and scoped persistence.
8. Run full regression, sandbox, failure-mode and cross-scope tests.
9. Create a draft integration PR only when the candidate is coherent; keep it unmerged until reviewed and explicitly approved.

## 5. Release boundaries

- No branch merge performed by this audit.
- No production database migration.
- No deployment or activation of remote providers.
- No multi-tenant or consumer application access is claimed.
- The new remote-provider flag is a conservative temporary gate; it is not a substitute for per-request and per-application privacy authorization.
- A successful CI run is evidence for that exact commit only, not a production security certification.
