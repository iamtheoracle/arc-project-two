# THE ORACLE-ARC

**A private, single-owner AI assistant powered by a locally hosted Ollama model.**

Oracle Arc is a standalone project. It is not Vantoris X Money, UNIBUD, The Arc Space, or a My Realm business application.

## Planned specialist agents

The architecture defines four coordinated roles: **BUD** (everyday companion and coordinator), **SPARK** (permissioned memory and continuity), **ORACLE** (reasoning, research and problem-solving), and **ORBITS** (visual understanding and creative workflows). They are intended to use one shared, provider-independent Oracle Arc service with separate identities and least-privilege permissions. This is an architecture direction, not a claim that the multi-agent runtime is already shipped.

## What is implemented

- Local inference through Ollama; default model: `qwen2.5:7b`.
- Owner-only HTTP API using a server-side bearer secret and constant-time token comparison.
- OpenAI-compatible chat endpoint: `POST /v1/chat/completions`.
- Persistent SQLite conversations and owner-managed memories.
- Memory list, save, and permanent-delete endpoints.
- Tool permissions default to denied. The owner must explicitly approve or revoke each installed tool.
- Tool audit history records approvals, revocations, denials, and executions without storing tool arguments.
- API model selection is pinned to the server-configured model; clients cannot trigger arbitrary model pulls.
- Human-understanding policy: Oracle Arc always replies in polished, correct English while adapting vocabulary, sentence length, detail, and examples to the conversation. It never copies a user's grammar or spelling errors.
- Owner-controlled communication profile for explanation detail, tone, and interests, persisted locally in SQLite.
- Personalization uses authorized conversation context and explicitly saved preferences; interests are optional context, not assumptions or mandatory themes.
- Conversation-led adaptation: the model uses the current conversation to form a temporary, revisable read of the user's goal, tone, familiarity, and support needs. It does not turn every remark into a permanent personality rule.
- Owner-controlled personal boundaries can be listed, added, and revoked. Saved profile, memory, and boundary text is treated as untrusted personal context, never as system policy.
- Automated tests for authentication, persistence, memory deletion, permissions, adaptive communication rules, and agent denial behavior.

## Run locally

Requirements: Python 3.11+ and [Ollama](https://ollama.com/).

```bash
# 1. Install and start Ollama using its official instructions.
ollama pull qwen2.5:7b

# 2. Create an isolated Python environment.
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt

# 3. Configure a server-only key. Do not commit .env.
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Put the generated value in ORACLE_ARC_API_KEY in .env.

# 4. Load the environment variables into this shell.
set -a
. ./.env
set +a

# 5. Start the API bound to loopback, not the public internet.
uvicorn api:app --host 127.0.0.1 --port 8090
```

The model must already be available in Ollama. Oracle Arc does not automatically download arbitrary models from API requests.

## API examples

Set `ORACLE_ARC_API_KEY` in the server environment and use the same value only in a trusted client:

```bash
export ORACLE_ARC_API_KEY='your-server-generated-secret'

curl http://127.0.0.1:8090/v1/chat/completions \
  -H "Authorization: Bearer $ORACLE_ARC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello, Oracle Arc."}]}'
```

Set communication preferences (optional; defaults are simple and natural):

\`\`\`bash
curl -X PUT http://127.0.0.1:8090/v1/profile \
  -H "Authorization: Bearer $ORACLE_ARC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"detail_level":"simple","tone":"natural","interests":["football","anime"]}'
\`\`\`

Oracle Arc uses these interests only when they genuinely help the conversation. The model must always use correct English; it adapts the complexity of its explanation, not its grammar or spelling.

Save a memory:

```bash
curl -X POST http://127.0.0.1:8090/v1/memories \
  -H "Authorization: Bearer $ORACLE_ARC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"content":"I prefer clear, direct explanations.","tags":["preferences"]}'
```

Other owner-authenticated routes:

- `GET /v1/profile` — view the communication profile.
- `GET /v1/boundaries` — list active personal boundaries.
- `POST /v1/boundaries` — save a clearly stated or confirmed boundary.
- `DELETE /v1/boundaries/{boundary_id}` — revoke an active boundary while retaining its audit history.
- `PUT /v1/profile` — update `detail_level` (`simple`, `balanced`, `detailed`), `tone` (`natural`, `warm`, `playful`, `professional`), and up to 30 interests.

- `GET /v1/models`
- `GET /v1/conversations`
- `GET /v1/memories`
- `PUT /v1/memories/{memory_id}` — edit a memory
- `DELETE /v1/memories/{memory_id}` — permanent deletion
- `DELETE /v1/conversations/{conversation_id}` — permanently delete a conversation and its messages
- `GET /v1/tools`
- `PUT /v1/tools/{tool_name}/approval` with `{"approved":true}` or `false`
- `GET /v1/audit/tools`

Conversation continuity: the first chat response returns `conversation_id`. Send it on later requests to continue that persisted conversation.

## Agent registry and connector routing

The authenticated agent API currently registers BUD and ORACLE. SPARK and ORBITS are present in the registry catalogue but remain disabled until their memory and visual runtimes are implemented.

- \`GET /v1/agents\` — list agent roles and configured connectors.
- \`POST /v1/agents/bud/chat\` — send a turn to BUD.
- \`POST /v1/agents/oracle/chat\` — send a turn to ORACLE.
- \`GET /v1/plugins\` — list plugin manifests and required permissions; this is a catalogue, not an execution endpoint.
- \\`POST /v1/implementation/plan\\` — submit a proposed implementation and receive transparent recommendations for agents, capabilities, plugins, extensions and connectors. Planning never installs, enables or executes an integration.

Agent chat accepts a messages array and an optional existing \`session_id\`. Session history is stored in the existing SQLite conversation store. SQLite is the primary session store. Set `ORACLE_ARC_SESSION_BACKUP_DB_PATH` to a different durable database file to enable a second SQLite store. Session history is copied when a backup session is first created, then new turns are mirrored; reads fall back to the backup if the primary read fails, and writes fall back to the backup if the primary write fails. Keep the backup on an independent disk or host to protect against machine or volume loss. Two SQLite files on the same disk are not protection against disk failure. This is synchronous application-level replication, not a distributed consensus system; restore and failover still require operational testing.

Set \`ORACLE_ARC_OLLAMA_FALLBACK_HOSTS\` to a comma-separated list of independent Ollama service URLs to enable model-connector failover, for example:

\`\`\`bash
ORACLE_ARC_OLLAMA_FALLBACK_HOSTS=http://ollama-backup:11434,http://ollama-secondary:11434
\`\`\`

BUD can explicitly delegate to ORACLE using the `delegate_to` field. It also has conservative automatic routing for clear research, analysis, debugging, comparison, design, and problem-solving requests. Everyday conversation remains with BUD. This is deterministic intent matching, not model-selected planning; inspect `handled_by`, `automatic_delegation`, and `delegation_reason` in the response.\n\nThe first configured host is attempted first; a failed connector is skipped for its cooldown period and the next configured host is tried. These backup services must already be running with the selected model available. No backup host is assumed or invented. If the variable is empty, there is no Ollama host failover. Optional remote fallbacks are available for OpenRouter, Groq, and Gemini through `ORACLE_ARC_OPENROUTER_API_KEY`, `ORACLE_ARC_GROQ_API_KEY`, and `ORACLE_ARC_GEMINI_API_KEY`; model overrides use the matching `ORACLE_ARC_*_MODEL` variables. Credentials stay server-side. Providers are only registered when their key exists, and no remote provider is enabled by default. Verify provider terms, data handling, region, and model availability before sending private prompts to a remote service.

Only the reviewed calculator module is currently in the executable built-in allowlist. File and system plugins are not exposed for execution. Arbitrary plugin discovery has been removed. Session message writes now carry unique event IDs so a retried mirrored write does not duplicate the same message in either SQLite store. The calculator runs in a one-shot rootless Podman container. Build the image with `podman build -f Dockerfile.plugin-worker -t oracle-arc-plugin-worker:local .` and run the API under an unprivileged account with rootless Podman available. The worker uses no network, a read-only root filesystem, no Linux capabilities, no-new-privileges, a non-root UID, process/memory/CPU limits, a small no-exec temporary filesystem, and a five-second host timeout. The API fails closed if Podman or the image is unavailable. Do not mount a privileged Docker socket into the API container. This is a stronger OS isolation boundary, but still requires host kernel/Podman updates, image provenance controls, and production threat-model review. Third-party plugins remain disabled. Tool approval remains default-deny.

## Security boundaries

- The API refuses protected requests if `ORACLE_ARC_API_KEY` is missing or incorrect.
- Keep `ORACLE_ARC_API_KEY` and the SQLite database on a trusted server. Never use a `VITE_*` or other browser-exposed variable for secrets.
- The API binds to `127.0.0.1` by default in the documented command. For a remote platform integration, use a private network or authenticated gateway with TLS; do not expose this port publicly without that layer.
- No tools are approved initially. Review each plugin before enabling it.
- Only the allowlisted calculator is executable. It runs in a separate rootless Podman container with no network and restricted resources; all other plugin types remain disabled.
- SQLite is local persistent storage, not encrypted-at-rest storage. Protect the host disk and backups.
- This repository's current GitHub visibility is public. Never put private conversations, memories, keys, or real personal data in source control. If source-code confidentiality is required, change repository visibility to private in GitHub settings.

## Verification

Run:

```bash
pytest -q
```

CI runs the same tests on pushes and pull requests. Passing tests validate the mocked API and permission boundaries; they do **not** prove that Ollama is installed, that a model has been downloaded, or that a live model response has been tested on your hardware.

## Status

This is the first implementation pass of the personal core. Real Ollama inference, remote platform integration, production hosting, and hardware performance still require environment setup and live verification.


## Durable agent task execution

Owner-authenticated task routes:
- `GET /v1/agent-tasks/{task_id}` — inspect task status and routing metadata.
- `GET /v1/agent-tasks?limit=50&status=queued` — list recent tasks, optionally filtered by status.
- `GET /v1/agent-queue/status` — inspect task/outbox counts and dead-letter backlog.
- `POST /v1/agent-tasks/{task_id}/cancel` — mark a queued or running task as cancelled. A running model HTTP call cannot yet be forcibly interrupted; the API prevents its late result from being saved. Finished tasks cannot be cancelled again.

Task claims use SQLite `BEGIN IMMEDIATE` transactions, worker ownership and expiring leases. Expired leases are recovered and requeued up to a bounded attempt count; tasks that exhaust the retry limit are marked failed. A worker can renew only its own unexpired lease, and only the lease owner can complete the task. The synchronous API path renews its lease while a long model call is active.

Task creation and lifecycle changes write transactional outbox events in the same database transaction. Outbox consumers claim events with expiring leases and acknowledge delivery. Delivery is at-least-once, so consumers must deduplicate by event ID. Events that exceed the bounded delivery-attempt limit are marked dead-letter and excluded from automatic claims for operator review.

**Current boundary:** the durable queue, leases and outbox primitives are implemented, but the HTTP chat route still runs agent work synchronously in the API process. A separately deployed worker service, broker-backed fan-out and cross-host database are not yet implemented. Multiple API instances must share the same transactional database; independent SQLite files on separate hosts do not coordinate claims.


### Implementation ownership and integration selection

Before a new feature is implemented, call the authenticated `POST /v1/implementation/plan` endpoint with a plain-language `description`. The planner returns:
- BUD as the coordination layer and a primary specialist (ORACLE for technical/reasoning work, SPARK for memory work, ORBITS for visual work).
- Required capabilities and the reason each capability matched.
- Candidate plugins, extensions and connectors, clearly marked as recommendations rather than installed or healthy services.
- Whether each selected specialist is currently registered and enabled.

The first planner uses transparent deterministic capability/keyword rules. It is not an autonomous model planner and does not prove that an integration exists. Recommendations must be reviewed against a trusted manifest, source provenance, version, permissions, data handling, sandbox requirements and health checks before installation or activation. External side effects require separate owner approval. Disabled agents remain disabled; the planner does not silently enable SPARK or ORBITS. Unsupported work must be reviewed rather than mapped to an invented integration.


### Trusted integrations and independent workers

#### Manifest trust

Place JSON manifests in `ORACLE_ARC_INTEGRATION_MANIFEST_DIR` (default: `data/integration-manifests`). Configure publisher verification keys server-side in `ORACLE_ARC_MANIFEST_TRUST_KEYS` as a JSON object mapping publisher IDs to secrets of at least 32 characters. Never expose these keys to browsers, manifests or worker task payloads. Configure the least-privilege permission allowlist with `ORACLE_ARC_ALLOWED_INTEGRATION_PERMISSIONS` as comma-separated permission IDs.

Manifests are data only. The manager verifies publisher HMAC signatures, semantic versions, app compatibility, capability and permission declarations, artifact SHA-256 digest, risk class and health-check URL shape. A trusted signature is not a security review of the artifact. The catalog reports health as `unknown` until a trusted integration-specific health adapter is wired. It does not download or execute artifacts.

- `GET /v1/integrations/catalog` — inspect signed manifests and compatibility.
- `POST /v1/integrations/{integration_id}/approval` — create an owner approval request for one eligible manifest version and digest.
- `PUT /v1/integrations/{integration_id}/approval?version=...&manifest_digest=...` — approve or reject the exact manifest version and digest.
- `GET /v1/integrations/approvals` and `GET /v1/integrations/audit` — review decisions and immutable-style append-only audit events.

Approval authorizes review for a future installation step only. It does not install, activate, grant runtime permissions or execute code. Reapproval is required if the manifest digest changes. Installation/activation remains disabled until a separate isolated installer, artifact provenance verification, health adapter and rollback process are implemented.

#### Independent agent workers

Start a worker process with:

```bash
python -m core.agent_worker
```

The API can enqueue work through authenticated `POST /v1/agent-tasks/submit` and returns a task ID. Workers use the same configured durable database, atomic claims, expiring leases, heartbeat renewal and bounded recovery. Configure `ORACLE_ARC_DB_PATH` to the shared database path accessible to both API and worker. SQLite is suitable for a single-host shared-volume deployment; it is not a cross-host coordination database. Multi-host workers require PostgreSQL or another shared transactional queue before production scaling.

Workers need the same server-side model/provider configuration as the API. They do not receive the owner API key from task payloads. Use a separate OS/service identity and restrict database, model and network access. The existing synchronous chat route remains synchronous; the submit endpoint is the independent-worker path.


#### Approved integration artifact staging (inert)

The owner may stage an exact, already-approved artifact after its bytes have been placed in a private server-side staging directory. This endpoint verifies the current trusted manifest, exact version and digest, and owner approval before copying the artifact atomically into the install directory.

Configure:
- `ORACLE_ARC_INTEGRATION_ARTIFACT_STAGING_DIR` (default `data/integration-artifact-staging`)
- `ORACLE_ARC_INTEGRATION_INSTALL_DIR` (default `data/integrations`)

Place the artifact at `<integration-id>-<version>.artifact` in the staging directory. The file must be a regular, non-symlink file no larger than 25 MiB. The service verifies SHA-256 while copying, stores it with owner-only file permissions, refuses replacement of an existing version, and records the action in the integration audit log.

Call the owner-authenticated endpoint:

```http
POST /v1/integrations/{integration_id}/install?version={version}&manifest_digest={digest}
```

**Important:** this is inert artifact staging, not code installation or activation. Archives are not extracted; modules are not imported; no process is launched; no runtime permissions are granted. Activation remains disabled until a reviewed integration-specific runtime adapter, isolated installer/executor, health checks, rollback and a separate owner activation decision exist. The artifact must be pre-positioned by a trusted operator; this endpoint does not fetch arbitrary URLs.


#### Separate activation approval

Staging an artifact does not authorize activation. A second owner decision is stored independently and bound to the same integration ID, version and manifest digest:

- `POST /v1/integrations/{integration_id}/activation-approval?version=...&manifest_digest=...` requests activation review. It requires a still-trusted manifest, prior installation approval, and a staged artifact whose bytes still match the manifest digest.
- `PUT /v1/integrations/{integration_id}/activation-approval?version=...&manifest_digest=...` records the separate owner decision.
- `GET /v1/integrations/activation-approvals` lists activation decisions.
- `DELETE /v1/integrations/{integration_id}/activation-approval?version=...&manifest_digest=...` revokes a previously approved activation decision and records the reason. Revoked decisions cannot pass the activation gate.
- `POST /v1/integrations/{integration_id}/activate?version=...&manifest_digest=...` currently fails closed with HTTP 409 because no reviewed integration-specific isolated runtime adapter is configured. It rechecks the live signed manifest, installation approval, activation approval and staged artifact digest on every attempt, then records the blocked attempt. Approval alone never starts code or grants permissions.

This separation is intentional: activation remains unavailable until the per-integration runtime adapter, permission broker, sandbox policy, health checks and rollback path have passed review and tests.


### Connected platform execution pipeline

The platform execution queue now has a dedicated worker runtime entrypoint:

```bash
export ORACLE_ARC_DB_PATH=data/oracle_arc.sqlite3
export ORACLE_ARC_WORKER_TOKEN='one-time-issued-worker-id.secret'
python -m core.platform_worker
```

The worker credential must be issued by the owner-authenticated worker provisioning endpoint and should be stored only in the worker service's secret manager/environment. It is bound to one tenant/application and can be revoked. Grant only `execution.claim`, `execution.complete`, and, for long-running inference, `execution.heartbeat`. Do not put the credential in source control, browser code, job payloads or logs.

The worker polls the application-scoped queue, claims a leased execution, rechecks the active agent version and pinned model route, verifies classification and region, and invokes the configured model gateway. Heartbeats renew an active lease during long model calls. Successful completion and provider-reported input/output token usage are committed together; late or cancelled results cannot overwrite a terminal execution. Policy and input-validation failures are not automatically retried. Other worker/provider failures use the queue's bounded retry/dead-letter policy.

The current execution runner supports text-only prompts/messages and the configured Ollama adapter. Agent manifests that declare tools are rejected by this runner until a scoped tool broker is implemented. Provider token counts are recorded only when the provider returns them; no fabricated estimates are written. This does not yet provide billing-grade pricing, cross-host queue coordination, or automatic production deployment.

For a single-host setup, API and worker must use the same protected SQLite database file and compatible model/provider configuration. For multi-host workers, migrate the control plane and queue to a shared transactional database before scaling. Start with a non-production tenant and test cancellation, worker revocation, provider timeouts, lease expiry and restart recovery before accepting real workloads.


### Project One connection and identity boundaries

Project One connects to the application-scoped control-plane API on this service:

- `GET /v1/platform/identity` resolves the authenticated application, tenant, principal and capabilities.
- `GET/POST /v1/platform/agents` and `/agents/versions` manage application-scoped agent versions.
- `GET/PUT /v1/platform/model-routes` manages model routes.
- `GET/POST /v1/platform/executions`, `GET /executions/{id}` and `POST /executions/{id}/cancel` manage workloads.
- `GET/PUT /v1/platform/quotas` and `GET /v1/platform/usage` expose quota and usage data.
- Owner tool grants are served separately at `/v1/tenants/owner/tool-grants`; they require the owner secret and must be called only by a trusted server-side Project One BFF. Application bearer credentials are never accepted for owner actions.

The legacy `/v1/tenants` customer API uses an older identity schema. It is deliberately isolated in `ORACLE_ARC_TENANT_IDENTITY_DB_PATH` (default: `data/oracle_arc_tenant_identity.sqlite3`). The Project One `/v1/platform` identity and execution control plane uses `ORACLE_ARC_DB_PATH`. Do not point both settings at the same SQLite file: their identity table layouts are not compatible. The owner tool-grant store remains on the platform database so grants are bound to Project One applications created by the platform owner-provisioning API.

Project One browser credentials are application-scoped and must be held only in memory or a trusted BFF. CORS is optional and exact-origin only; prefer the same-origin BFF for production owner actions. The scoped broker is now wired into the platform worker model-call loop. The initial trusted registry exposes only `tool.calculate`, executed through the existing isolated rootless-Podman plugin worker. A tool is visible and callable only when the agent manifest, the active application-principal credential, the active owner grant, and the worker credential all authorize it. Other tool IDs remain unavailable until a reviewed handler is registered server-side and covered by isolation tests. Worker credentials that need calculator access must explicitly include `tool.calculate`; application credentials must independently include the same capability.


### Durable execution event stream

`GET /v1/platform/executions/events?after=<event_id>&duration_seconds=50` returns an authenticated Server-Sent Events stream. Lifecycle events are written by SQLite triggers to `arc_execution_events`, so reconnecting with the last event ID replays updates without relying on in-memory process state. The stream is scoped to the authenticated tenant, application and principal, revalidates the application credential periodically, sends keepalives, and closes after a bounded lifetime so clients can reconnect. Project One uses fetch-based streaming because native browser EventSource cannot attach its in-memory bearer credential.

### Worker tool permissions

For a calculator-enabled agent, all four independent grants are required:

1. Agent manifest `allowed_tools` contains `tool.calculate`.
2. At least one active application credential for the execution principal contains capability `tool.calculate`.
3. The owner has an active `tool.calculate` grant for the same tenant/application.
4. The worker credential was issued with `tool.calculate` in addition to execution lifecycle capabilities.

The worker re-reads application capabilities and owner grants before each tool call and revalidates the worker credential. Tool schemas are generated from the trusted server registry; model output cannot add tools or handlers.


Remote provider egress is deliberately fail-closed: OpenRouter, Groq and Gemini routes may be configured only for `public` data until a provider-specific contract, region and data-egress policy is approved. Ollama remains the local route for private data. The OpenAI-compatible adapters preserve tool-call IDs and usage accounting; tool function names are normalized to provider-safe names and resolved back to immutable internal tool IDs.


See [the deployment runbook](docs/DEPLOYMENT_RUNBOOK.md) for the current single-host API/worker topology, persistent SQLite constraints, rootless Podman isolation, environment configuration and go-live checklist. Production deployment is not complete until that runbook is executed against a real host.

## Permission-scoped documents and ORBITS media processing

Application credentials can use the scoped document endpoints under `/v1/platform`:

- `POST /documents` indexes already-extracted text (requires `document.index`).
- `GET /documents/search?query=...` searches only the authenticated principal/application scope (requires `document.search`).
- `DELETE /documents/{document_id}` tombstones a document in that same scope (requires `document.delete`).
- `POST /documents/upload` quarantines a PDF/plain-text file, requires a successful ClamAV scan, extracts it in the isolated worker, and indexes only scanner-clean text. It requires `orbits.process` and `document.index`.
- `GET /documents/quarantine/{asset_id}/audit` returns scope-filtered quarantine events (requires `document.audit` or `document.delete`).
- `DELETE /documents/quarantine/{asset_id}` removes quarantined bytes and writes a deletion audit event (requires `document.delete`).

For binary input, build the separate isolated ORBITS worker image:

```bash
bash scripts/build-orbits-worker.sh
```

Set `ORACLE_ARC_ORBITS_WORKER_IMAGE=oracle-arc-orbits-worker:local` on the API host. The image must already be present locally; runtime execution uses Podman with `--pull=never`, no network, a read-only root filesystem, dropped Linux capabilities, non-root execution, resource limits and a hard timeout. Missing Podman or image fails closed.

`POST /v1/platform/orbits/process` requires the `orbits.process` capability and accepts base64-encoded file bytes plus a processor ID:

- `document.extract`: extracts text from PDF or UTF-8 plain text using `pypdf` for PDF files.
- `image.ocr`: runs image OCR using Pillow and Tesseract.
- `audio.inspect`: reads supported audio container/codec metadata using Mutagen. This processor does not transcribe speech.
- `audio.transcribe`: a separate, optional faster-whisper worker. It is registered only when a complete local model directory is provisioned. The worker mounts model files read-only, runs without network access, sets Hugging Face offline flags and has no remote fallback. See [local ASR setup](docs/LOCAL_ASR_MODEL_SETUP.md).

Set `index_text: true` to index extracted PDF/plain-text or OCR text. This additionally requires `document.index`. The resulting document is stored with the authenticated tenant, application and principal scope. Audio metadata cannot be indexed as a transcript.

Document uploads are stored under a private quarantine directory and scanned with ClamAV. Missing, timed-out or indeterminate scanner results fail closed. Both quarantined bytes and indexed extracted text have bounded retention; run `python scripts/expire-document-retention.py` periodically (for example, from a host scheduler) to enforce expiry even when no API traffic occurs. The default quarantine retention is seven days; indexed text defaults to one year unless a shorter per-upload value is supplied. The media upload request budget is separately bounded by `ORACLE_ARC_MEDIA_MAX_REQUEST_BYTES`.

The container is a processing boundary, not a guarantee of perfect extraction. Validate OCR accuracy, document parsing, ASR quality and media compatibility against representative and adversarial files before production use. Real ASR inference and real target-host Ollama verification remain separate release gates; use `scripts/verify-local-asr.py` and `scripts/verify-local-runtime.py` after installing the model and configuring the host.

## Engineering acceptance standard

All new features and releases must satisfy the [Oracle Arc engineering acceptance standard](docs/ENGINEERING_ACCEPTANCE_STANDARD.md). Passing an isolated unit test or discovering a model/processor is never treated as proof of production readiness.
