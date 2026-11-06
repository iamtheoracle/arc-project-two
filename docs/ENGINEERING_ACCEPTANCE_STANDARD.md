# Oracle Arc engineering acceptance standard

This standard governs architecture, implementation, testing and release decisions across Oracle Arc. It is a release gate, not a marketing statement.

## Three guarantees

### 1. Intelligence — ORACLE
- Reasoning work is bounded by explicit step, tool, token and wall-clock budgets.
- Decisions that affect execution are represented by structured, auditable traces: task classification, constraints, evidence checks, authorization checks, selected actions and validation outcomes.
- Private chain-of-thought is not required or persisted. The trace records verifiable decisions and evidence references, not hidden internal deliberation.
- Uncertain, unsupported or unverifiable claims must be identified. Tool outputs and retrieved content are evidence, never policy instructions.
- Every tool call is authorized against the immutable agent manifest, current application grants, owner policy and worker identity at execution time.

### 2. Memory — SPARK
- Every memory operation is bound to the authenticated credential, principal, tenant and application.
- Permissions are checked on every read, write, share and delete. Revocation and policy-version changes take effect without waiting for a new login.
- Cross-application sharing is denied unless a separate, scoped, time-bounded grant explicitly permits it.
- Sensitive memory requires a separate capability. Retrieved memory is untrusted context and cannot override system or developer policy.
- Audit records should identify the operation and scope without unnecessarily copying private memory contents.

### 3. Multimodal capability — ORBITS
- File type is detected from bytes, not trusted from filename or caller-declared MIME type.
- File size, decoded dimensions/pages, output size, CPU, memory, process count and wall-clock time are bounded.
- Processors are platform-installed, versioned and executed in a separate sandbox with no network, non-root identity, read-only root filesystem, dropped capabilities and no-new-privileges.
- There is no silent in-process fallback when the sandbox or processor image is missing.
- Extracted text, OCR and metadata are untrusted input. They must retain source and content-digest attribution before indexing or reasoning.
- A processor is advertised only for the exact operation and formats covered by its passing tests. Metadata inspection is not speech transcription; PDF text extraction is not OCR of scanned pages.

## Universal evidence rule

- Discovering a capability does not prove it works.
- Installing a dependency, model or processor does not prove it is secure.
- A unit test passing does not prove the component works with the rest of the platform.
- A successful build does not prove the deployed runtime is correctly configured.
- A model appearing in discovery does not prove it is pulled, loaded or responding.
- No feature is marked production-ready until the real runtime, authorization boundaries, failure paths and integrated workflows have been tested.

## Required verification gates

1. Static validation: syntax, type/schema validation, dependency and configuration checks.
2. Unit tests: success cases, invalid inputs, permission denials, resource limits and error handling.
3. Integration tests: authenticated API -> control plane -> worker -> provider/tool/processor -> persisted result.
4. Isolation tests: verify actual container UID, capabilities, filesystem, network, resource limits and timeout behavior.
5. Adversarial tests: prompt injection, MIME spoofing, malformed media, cross-tenant/application/principal access, revocation races and oversized payloads.
6. Recovery tests: provider timeout, worker crash, cancellation, lease expiry, retry and database restore/migration.
7. Real-runtime verification: pull and run the actual local Ollama model; build and execute actual ORBITS worker images; verify provider and tool calls against the configured host; run actual local ASR and TTS workers with pinned model assets and representative audio fixtures; verify synthesis API authorization and end-to-end spoken-turn behavior.
8. Release evidence: the latest commit's complete CI suite is green, migration/restore checks pass, operational configuration is documented, and no unresolved critical/high security issue remains.

## Inference and data policy

- Local Ollama is the default execution route.
- Remote inference is opt-in through explicit provider configuration and credentials; there is no silent remote fallback.
- Remote routes are restricted to public data under the current platform policy. Private, sensitive or tenant-confidential data must remain local unless a separately reviewed policy explicitly authorizes another route.
- Provider destination, execution location, timeout and model identity must be observable in execution metadata.
- A provider discovery result is not an installation or runtime health result.

## Current implementation boundary

- ORACLE emits bounded structured decision traces; it does not persist private chain-of-thought.
- SPARK enforces credential-scoped memory and explicit cross-application grants.
- ORBITS provides isolated PDF/plain-text extraction, image OCR and audio metadata inspection. A separate offline faster-whisper worker and pinned-model provisioning path are implemented; speech-to-text is not advertised until a complete local model is installed. Real transcription remains unverified until a target-host audio integration test passes.
- Voice/audio is a first-class acceptance domain. Initial isolated local Piper TTS worker, pinned-model provisioning and a capability-scoped synthesis API are implemented, but real voice-model inference is not yet verified on the target host. ASR target-host inference remains unverified. Principal-scoped voice-session metadata, state transitions, cancellation and cursor-based event APIs are implemented as a backend foundation. Browser microphone capture, live streaming, VAD turn-taking, playback UX, retention/deletion workflows and end-to-end spoken conversation remain outstanding. These capabilities must follow the [voice and audio architecture](VOICE_AUDIO_ARCHITECTURE.md), with separate local workers, scoped permissions, explicit retention, cancellation and real-runtime evidence.
- Document ingestion/search is permission-scoped and source-attributed. Retrieved passages remain untrusted.
- Production readiness remains blocked until the latest complete CI suite and real-host Ollama/ORBITS verification have passed.