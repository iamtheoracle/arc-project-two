# Oracle Arc execution integration phase — 2026-11-01

**Branch:** `feat/arc-owner-tool-grants-and-console-api`  
**Status:** implementation committed; CI verification pending  
**Scope:** authenticated SPARK context, bounded ORACLE policy, secure document search, ORBITS media intake, execution fencing.

## Implemented in this phase

### SPARK: authenticated memory context

- Execution records now persist the exact submitting `credential_id` and `policy_version`.
- Additive migrations add those columns to existing databases. Legacy queued executions without an attributable credential fail closed rather than inheriting another credential.
- Worker execution context revalidates that exact credential, principal, tenant, application, application policy version, and active statuses.
- Tool capability resolution now reads only the exact submitting credential; it no longer unions capabilities from every credential belonging to the same principal.
- SPARK memory is opt-in per execution through `spark_memory: { enabled: true, categories: [...] }`.
- Memory retrieval is bound to the authenticated principal + tenant + application. Sensitive memory requires `spark.memory.sensitive`. Cross-application sharing is not implicitly included in worker prompts.
- Retrieved memory is explicitly framed as untrusted data. Trace metadata contains memory IDs and categories, not memory contents.

### ORACLE: bounded, auditable reasoning policy

- The worker now applies the existing request assessment and reliability policy to each execution.
- The model receives a four-phase decision procedure: identify outcome/constraints, check evidence/permissions/uncertainty, select authorized actions, validate and communicate limitations.
- The persisted execution result includes a structured `reasoning_trace` with task class, risk level, required checks and the bounded procedure.
- Private chain-of-thought is not captured or persisted.

### Secure document retrieval

- Added tenant/application/principal-scoped document indexing and lexical retrieval.
- Each indexed document retains title, source URI, content digest, classification and lifecycle state.
- Search revalidates the exact live credential and capability on each request.
- Sensitive documents require a separate read grant.
- Retrieval results carry source IDs, source URIs and SHA-256 digests.
- Retrieved passages are serialized as JSON and clearly marked as untrusted source data.
- Installed `tool.document_search` in the trusted worker registry. It requires the immutable agent manifest, the application credential capability, the owner tool grant and the worker capability. The handler re-resolves the exact submitting credential before retrieval.
- Raw search queries are not written to the audit table; only a query digest and result count are retained.

### ORBITS: controlled media intake

- Added byte-signature media detection for PNG, JPEG, GIF, WebP, WAV, MP3, OGG, PDF and plain text.
- Upload metadata is bounded; detected type must match any declared MIME type.
- Rejects active SVG/HTML/XML markup, binary archives, path-like filenames and unsupported formats.
- Added a dedicated ORBITS worker image with PDF/text extraction (`pypdf`), image OCR (`Pillow` + Tesseract), and audio-container metadata inspection (`mutagen`).
- All three handlers are platform-registered and invoke a separate rootless Podman container with no network, read-only root filesystem, dropped capabilities, no-new-privileges, non-root UID, memory/CPU/PID limits, bounded temporary storage and a 60-second wall-clock deadline. There is no in-process fallback.
- The authenticated `/v1/platform/orbits/process` API requires `orbits.process`; extracted text can be indexed only when the same credential also has `document.index`.
- Audio transcription is deliberately not claimed: audio inspection returns container/codec metadata and explicitly reports `transcription_status=not_installed`. Speech-to-text requires a separately installed and verified local ASR model/processor.
- Image OCR and PDF extraction are real processing paths, but accuracy, multilingual OCR quality, encrypted/complex PDF handling and adversarial-file resilience still require validation against representative corpora.

### Deadlines, cancellation and provider timeouts

- Worker executions use `ORACLE_ARC_EXECUTION_TIMEOUT_SECONDS` (default 300 seconds; accepted range 1–3600).
- Deadline checks run before model rounds, after provider responses, before tool calls and before completion.
- The worker revalidates the execution lease and authenticated identity after provider inference; a cancelled or revoked execution is fenced from tool execution and completion.
- Existing Ollama provider timeout remains bounded by `ORACLE_ARC_OLLAMA_TIMEOUT_SECONDS` (default 120 seconds; max 900). Remote HTTP adapters use their configured bounded HTTP timeout (default 30 seconds).
- Cancellation cannot forcibly interrupt a synchronous provider request already in flight; the provider timeout bounds how long that request can remain blocked. A cancellation is enforced immediately when control returns to the worker.
- Existing lease recovery, retry, dead-letter and concurrent-claim protections remain in place.

## Verification added

New worker tests cover:
- exact-principal SPARK memory retrieval and no cross-principal leakage;
- memory opt-in and missing permission denial;
- ORACLE trace output and bounded decision steps;
- cancellation during provider inference;
- source-attributed document search through the authenticated worker tool;
- credential revocation without fallback to a second credential belonging to the same principal.

New retrieval and ORBITS tests cover:
- document permission and application/principal scoping;
- source attribution, content digests and prompt-injection framing;
- credential revocation and sensitive-data grants;
- media type sniffing, MIME spoofing, active markup/archive rejection;
- trusted processor registration and asset digest revalidation.

## Still open

1. Run the complete GitHub Actions suite, including the new real ORBITS container integration tests, and resolve every failure. No passing CI result is claimed until GitHub reports success for the latest commit.
2. Complete production-grade document upload UX, ingestion quotas, malware scanning and retention policy. The authenticated text-ingestion/search/delete API and ORBITS PDF/image extraction-to-index path are now implemented.
3. Add a separately packaged, locally hosted ASR processor and model before claiming audio transcription. Expand OCR/PDF tests with multilingual and adversarial corpora.
4. Add process-level cancellation for providers and tools where supported; current worker cancellation fences results after synchronous calls return.
5. Run cross-component adversarial tests, migration/restore drills and deployment tests.
6. On the actual Ollama host, run `bash scripts/verify-local-ollama.sh`. It refuses non-loopback endpoints, pulls `qwen2.5:7b` (the current platform test route), checks model metadata and performs a real `/api/chat` inference. Then run the worker tool-call integration tests on that host. Model discovery is not installation or proof of a running model.

## Inference policy

- Local Ollama remains the intended default.
- Remote providers require an explicitly configured provider route and credentials; the current platform route policy restricts them to public data and does not silently fall back from local to remote.
- No remote provider is enabled by default.
- No production deployment, customer traffic, or consequential external action is enabled by this phase.
