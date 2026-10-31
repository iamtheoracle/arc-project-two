# Oracle Arc — Engineering and Security Audit (2026-10-31)

## Scope

Audit of the current feature branch implementation, focused on the model gateway, API boundaries, plugin execution, persistence, and privacy claims. This is a source review plus automated CI; it is not a penetration test, live-host test, or production certification.

## Changes made in this pass

- Remote Ollama endpoints are no longer silently described as local. Loopback/localhost is the default trust boundary.
- Remote Ollama is disabled unless `ORACLE_ARC_ALLOW_REMOTE_OLLAMA=true`; when enabled, HTTPS is required and the public capability manifest reports `execution_location=remote`.
- `OLLAMA_HOST` is validated as an HTTP(S) URL and embedded URL credentials are rejected.
- Provider registration now validates the provider manifest, ID, execution location, capability object, and callable chat implementation.
- The gateway now enforces declared tool-calling and streaming capabilities and validates basic message shape, model ID, and temperature bounds before dispatch.
- The in-memory per-IP rate-limit bucket map now has a hard 10,000-key ceiling to prevent unbounded growth from attacker-controlled client keys.
- Added tests for remote-host denial, HTTPS enforcement, remote-location disclosure, malformed host URLs, gateway capability enforcement, malformed messages, and invalid temperatures.

## Findings and risk register

| Severity | Finding | Status |
|---|---|---|
| Critical | Python plugins execute inside the API process and are not OS-sandboxed. | Mitigated by default-deny; isolated worker remains a release blocker. |
| High | A remote Ollama URL could previously be mislabeled as local, undermining privacy expectations. | Fixed with explicit opt-in, HTTPS requirement, and remote manifest disclosure. |
| High | In-memory rate limiting is process-local and cannot protect multi-worker deployments consistently. | Documented limitation; use a trusted gateway/shared limiter before multi-worker exposure. |
| High | Tool approval is keyed by tool name, not a digest/version of its code and schema. A changed plugin could inherit a prior approval. | Open; approval fingerprinting is required before enabling plugin execution beyond tightly controlled development. |
| High | API bearer secret is a single static owner credential; there is no rotation workflow, session lifecycle, or revocation store. | Open; suitable only for private single-owner deployment behind a trusted network boundary. |
| High | SQLite is not encrypted at rest; backup/restore and migration versioning are not implemented. | Open; protect host storage and backups; add migrations and recovery tests. |
| Medium | Model manifest capabilities are declared by adapters and are not yet empirically probed against each installed model/checkpoint. | Partially improved by gateway enforcement; per-model capability discovery and conformance tests remain. |
| Medium | Ollama host validation classifies explicit loopback names as local but does not pin DNS resolution or defend against a compromised local resolver/proxy. | Residual host/network trust assumption; use loopback endpoint and OS/network controls. |
| Medium | API request-rate controls are in-memory and client-IP based; proxy deployments must correctly define trusted client identity. | Documented; gateway must sanitize forwarding headers and own rate limits. |
| Medium | No live Ollama inference, remote provider, hardware performance, or network isolation test has been performed. | Open; requires owner environment. |
| Medium | SPARK memory is currently injected as a bounded flat list, without provenance, sensitivity labels, expiry, conflict resolution, or retrieval ranking. | Open; implement typed memory contract before autonomous memory learning. |
| Medium | Agent loop has bounded steps but no durable task checkpoints, cancellation, idempotency, or independent verifier. | Open; needed before reliable multi-step execution. |

## Release gates

1. Keep in-process plugins disabled in production.
2. Implement a restricted tool worker with OS-level identity, filesystem/network policy, resource limits, narrow RPC, timeout, and cancellation.
3. Bind tool approvals to immutable plugin/schema fingerprints and revoke approvals automatically when fingerprints change.
4. Add database schema migrations, WAL/concurrency strategy, encrypted backup policy, and tested restore procedure.
5. Add owner credential rotation and trusted-gateway deployment guidance with TLS, rate limiting, and trusted-proxy rules.
6. Implement model-specific capability conformance and a deterministic evaluation suite before activating remote providers or the multi-model council.
7. Implement SPARK provenance/sensitivity/expiry and task checkpointing before autonomous memory writes or consequential workflows.

## Verification

- Latest CI verification on the current branch head: **50 tests passed, 1 upstream Starlette/httpx deprecation warning**. Both push and pull-request workflow runs completed successfully: [run 548](https://github.com/iamtheoracle/arc-project-two/actions/runs/41215308732) and [run 549](https://github.com/iamtheoracle/arc-project-two/actions/runs/41215313182).
- Two earlier CI attempts failed because the new URL-validation test used an unescaped regular-expression pattern. The assertion was corrected and the current-head runs passed.
- No live Ollama request, external provider request, penetration test, or production deployment is claimed.

## Decision

Continue development on the feature branch. Do not merge or expose the service publicly based only on unit-test success. The next engineering priorities are approval fingerprinting, isolated tool execution, and persistent storage migration/backup controls.