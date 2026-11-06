# Oracle Arc (v0.1)

Oracle Arc is an **independent AI core**. UNIBUD and other My Realm applications consume it through an
authenticated API; it is not a UNIBUD screen and not another name for Bud. Python 3.11+, **standard
library only** (no install step, no vendor lock-in).

```
Application (UNIBUD ...) ──token──▶ API gateway ──▶ ORACLE pipeline ──▶ Model gateway ──▶ Ollama (local) | remote (opt-in)
                                         │              │  ├─ SPARK  scoped memory
                                         │              │  ├─ ORBITS controlled media
                                         │              │  └─ Tools (granted per agent) ─▶ confirmation ─▶ execute ─▶ verify
                                         └──────────────┴───────────────▶ hash-chained audit log
```

## Module map

| Responsibility | Module | What it guarantees (and the test that proves it) |
|---|---|---|
| Identity | `identity.py` | Apps authenticate with a secret (scrypt-hashed); tokens bind app+user, are HMAC-signed, expire, and can be revoked per app. An app cannot mint tokens for another app. (`test_foundation`) |
| API gateway | `gateway.py` | Bearer auth on every route except `/v1/health` and `/v1/token`; body size cap; no internal error leakage. (`test_http`) |
| Model gateway | `models/` | Local-first routing, fallback, circuit breaker, latency-aware ordering, per-app token/cost quotas, cache for deterministic requests. **Remote models are off by default and are never used for data above the configured class ceiling.** (`test_models`, `test_backends`) |
| ORACLE | `oracle.py` | Pipeline: identify → permitted context → understand (deterministic fast path, else model) → policy → grant check → confirmation → execute → **verify** → audit. Model output is untrusted: tool names and arguments are validated strictly. (`test_pipeline`) |
| SPARK | `spark.py` | Memory is partitioned by application, user and *space* (`unibud/flow`, `unibud/bud`). Bud cannot read Flow data unless the user shares it, and the share is revocable. Task memory expires. (`test_spark`) |
| ORBITS | `orbits.py` | Size limits, real-content sniffing (declared type must match), executable/script/archive rejection, pluggable scanners that **fail closed**, owner-only access, retention sweep. (`test_orbits`) |
| Agents | `agents.py` | Versioned (must increase), lifecycle (`active/suspended/retired`), health checks, risk ceiling per agent. |
| Tool grants | `tools/registry.py` | `(agent, tool)` grants with immediate revocation. Concierge may search and quote; it cannot charge without a confirmed, verified booking. |
| Confirmation | `confirmation.py` | Bound to the exact action by hash; single-use; expiring; same user and app only; high-risk actions need a step-up authenticator and **fail closed without one**. Grants/agent state are re-checked at execution time. |
| Audit | `audit.py` | Append-only SHA-256 hash chain; edits and deletions are detectable; secrets redacted; prompt content is never logged. |

## Behaviour rules enforced in code

* Understanding a request never implies permission to execute it.
* A financial/destructive action requires explicit confirmation **and** step-up, then is executed with an
  idempotency key (the confirmation id), then **verified against the provider**. If the provider does not
  confirm, the response is `unverified`, never "success".
* Tools with no connected provider return `unavailable`. Nothing is invented: not providers, prices,
  availability, balances, order status or payment outcomes. Figures in a model reply that did not come from
  the user, memory or a tool are blocked (`ungrounded_figures`).
* Deterministic operations (e.g. arithmetic) do not call a model at all.

## API

| Route | Auth | Purpose |
|---|---|---|
| `POST /v1/token` | app secret | `{app_id, app_secret, user_id, ttl?}` → `{token}` |
| `POST /v1/chat` | bearer | Full pipeline: `{agent, message, conversation_id?, remember?, data_class?}` |
| `POST /v1/confirm` | bearer | `{confirmation_id, action_hash, proof?}` completes a confirmed action |
| `POST /v1/complete` | bearer | Governed raw completion for hosts that build their own prompts: `{agent?, messages[], max_tokens?, data_class?}`. No tools, no memory writes. |
| `POST /v1/memory/share`, `/unshare` | bearer | The user grants/revokes read access between memory spaces |
| `GET /v1/agents` | bearer | Agent and model-backend health |
| `GET /v1/health` | none | Liveness only |

Statuses: `answered`, `completed`, `needs_confirmation`, `unverified`, `failed`, `denied`, `unavailable`, `quota_exceeded`.

## Run

```bash
export ARC_SERVER_KEY="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"   # required (>= 32 chars)
export ARC_APP_ID=unibud ARC_APP_SECRET="<long random secret>"
ollama pull qwen2.5:7b                     # initial local model direction
python3 -m oracle_arc                      # http://127.0.0.1:8787
```

Optional remote provider (opt-in; keep `ARC_REMOTE_MAX_DATA_CLASS=PUBLIC` unless policy says otherwise):
`ARC_ALLOW_REMOTE=1 ARC_REMOTE_URL=... ARC_REMOTE_MODEL=... ARC_REMOTE_API_KEY=...`

Tests: `python3 -m unittest discover -s tests -t .`

## Verification status (be precise about what this does and does not prove)

* **Run and passing:** 93 unit/integration tests, including real HTTP round-trips and a mutation check
  (ten deliberate security regressions were each caught by the suite).
* **Not run:** against a real Ollama server or a real remote provider (none available in the build
  environment). The backends are tested for request shape and response parsing against stand-in servers only.
  Model quality (planning reliability of a 7B model, tool-call accuracy) is **unmeasured**.
* **Not production-ready without these:**
  * Identity provider decision (Auth0/Entra/Okta/Google/OIDC) is still open. Today the calling application
    vouches for its user ids (`TrustedAppAssertion`); swap in an OIDC verifier before real users.
  * App registry, grants and agent state are in-memory (re-registered at start-up); only the audit log and
    SPARK memory persist (SQLite). Multi-process deployment needs a shared store.
  * The built-in malware scanner detects only the EICAR test string. Use `ClamdScanner` (implemented, tested
    against a protocol stand-in) with a real ClamAV for production.
  * ORBITS has no audio/vision/OCR processors yet; those requests return `unavailable` until one is registered.
  * No streaming responses, no rate limiting per IP, no TLS (put it behind a reverse proxy on a private network).
  * Concierge provider adapters (transport, etc.) are contracts only; none are connected.

## Legacy code

`core/`, `main.py`, `web.py`, `plugins/` are the earlier single-user CLI and are left untouched. They are
superseded by `oracle_arc` and have known weaknesses (the `files` plugin can read any local path; the calculator
accepts unbounded exponents). Do not expose them on a network.
