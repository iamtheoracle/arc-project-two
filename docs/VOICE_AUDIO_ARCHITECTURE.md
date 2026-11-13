# Oracle Arc voice and audio architecture

## Status and scope

Voice and audio are a first-class product capability, not a side effect of document/media ingestion. The existing ORBITS audio metadata inspector and optional local faster-whisper worker are only foundations. They do not constitute a complete voice conversation system. This document defines the implementation boundary and release gates for the end-to-end voice experience.

The default data path is local. Audio must never be sent to a remote provider unless a future explicit, per-session opt-in policy authorizes the exact destination and data classification. Missing local models, workers or devices must fail visibly; they must never trigger silent remote fallback.

## Product capabilities

### 1. Microphone capture and audio intake

- A client requests microphone permission only after the user starts a voice action.
- Show a clear recording state while the microphone is active; provide an immediate stop/cancel control.
- Capture audio in bounded chunks with explicit codec, sample-rate, channel-count and duration metadata.
- Validate actual container/codec bytes, not filename or client-declared MIME type.
- Enforce per-chunk, total-session, duration, sample-rate, channel-count and decoded-size limits before processing.
- Reject malformed, truncated, unsupported and over-budget media with actionable errors.
- Do not persist raw audio by default. If retention is enabled, require a distinct user choice and an expiry.

### 2. Speech detection and transcription

- Keep voice activity detection (VAD) separate from transcription so silence trimming and endpoint detection can be tested independently.
- Use the separately provisioned, pinned, local ASR worker as the first transcription backend.
- Return transcript text with language, confidence where available, duration, model identity/revision, timestamps when enabled, and an explicit local inference marker.
- Preserve segment boundaries and timestamps rather than flattening every recording into one untraceable string.
- Treat transcripts as untrusted user content. Never interpret spoken text as system or developer instructions.
- Support explicit language selection and a tested automatic-language mode; do not claim support for languages that have not passed the corpus tests.
- Distinguish an audio metadata inspection result from a transcript in API schemas and user-facing status.

### 3. Voice conversation orchestration

- A voice turn has a durable session ID and turn ID, a bounded lifecycle, and explicit states: created, capturing, uploaded, transcribing, awaiting_model, synthesizing, ready, playing, interrupted, cancelled, failed and completed.
- The transcript is passed to the same authenticated conversation context used by text chat; identity, tenant, application, principal and capability scope must not change when switching modalities.
- ORACLE receives the transcript as user content, not as an instruction-bearing tool or policy message.
- Responses retain their text form even when speech synthesis is unavailable.
- Each stage emits durable, ordered status events. Clients can reconnect from an event cursor without duplicating a turn.
- Cancellation and interruption are idempotent. A cancelled turn cannot later publish audio or overwrite a terminal state.
- Retries are bounded and stage-aware; non-repeatable capture and playback actions are never replayed automatically.

### 4. Speech generation and playback

- Add a separately provisioned local text-to-speech (TTS) worker and voice model; do not bundle model downloads into request handling.
- Pin model revision, license/provenance and SHA-256 integrity manifest. Mount voice assets read-only into a non-root, network-disabled worker.
- Expose a finite reviewed voice catalogue with language, locale, sample rate, speaker identity and model version. Do not accept arbitrary filesystem paths or model IDs from clients.
- Return audio as a bounded, typed artifact with content digest, codec, sample rate, duration and generation location.
- Support cancellation, output-size and synthesis-time budgets, and cleanup/retention policy.
- Never claim generated audio is ready until the worker has completed and the output has passed format and integrity validation.
- Text remains visible and copyable; voice is an additional presentation, not a replacement for the answer.

### 5. Live voice and turn-taking

- Implement streaming as a later phase after reliable bounded request/response transcription and synthesis are verified.
- Use explicit turn-finalization rules, silence thresholds, maximum utterance duration and a user-controlled push-to-talk mode.
- Playback interruption must stop the active output promptly and prevent stale audio chunks from continuing.
- Handle half-duplex operation first. Full-duplex barge-in is a separate acceptance gate requiring echo cancellation and acoustic testing.
- Never infer that a user has finished speaking from a single fixed silence threshold without a tested, configurable policy.

### 6. Audio utilities and media workflows

- Keep audio inspection, transcription, speech synthesis, diarization, enhancement and format conversion as distinct processor IDs and capabilities.
- Do not register diarization, speaker identification, noise removal, translation or voice cloning until their dedicated processors, consent rules and tests exist.
- Speaker diarization, if added, must use neutral speaker labels (for example, Speaker 1) and must not identify a real person.
- Do not build voice cloning or biometric identity verification into the default voice stack.
- Preserve source digest and provenance through derived artifacts. Derived transcripts and audio must inherit the source's scope and retention policy.

## Security, privacy and authorization

- Microphone permission is a client-side device permission; server authorization is independently required for upload, transcription, conversation, synthesis and retention.
- Use separate least-privilege capabilities such as audio.capture, audio.transcribe, audio.synthesize, audio.read and audio.retain. No capability is implied by another.
- Revalidate credentials and grants before each stage and before publishing derived results.
- Bind all session, transcript and generated-audio records to the authenticated tenant/application/principal scope. Never accept caller-supplied scope identifiers as authority.
- Encrypt transport and protect stored artifacts at rest using the deployment's approved storage controls.
- Do not log raw audio, transcript bodies, API secrets or generated audio. Audit event metadata, digests, processor/model versions, authorization decisions and lifecycle outcomes.
- Apply data minimization: raw audio is ephemeral by default; transcript retention and audio retention are separately configurable.
- Deletion must remove stored bytes and derived content or create an explicit tombstone where immutable audit requirements apply.
- Audio prompts and transcripts are untrusted input. Prompt-injection text spoken in a recording cannot override policy or grant permissions.

## API contract direction

The final route names may be refined during implementation, but the interface must provide equivalent operations:

- Create a scoped voice session and receive a session ID.
- Upload bounded audio or append bounded chunks to an active session.
- Finalize capture and start transcription.
- Read transcript and stage status for an authorized session.
- Submit the transcript to the authenticated conversation with the same conversation identity as text mode.
- Request synthesis for an authorized response using a server-approved voice ID.
- Fetch generated audio through a scoped, short-lived artifact reference.
- Cancel or interrupt a turn and observe the terminal state.
- Subscribe to durable session events with cursor-based reconnect.

Do not expose raw worker endpoints to browsers. Clients call the authenticated API/BFF; the API dispatches to platform-installed isolated workers.

## Implementation phases

1. **Harden current audio foundation:** correct format detection and codec validation, test malformed/oversized inputs, ensure ASR manifest validation covers every required model asset, and add real container integration coverage.
2. **Local TTS foundation:** implemented initial Piper worker, pinned model provisioning, capability-scoped API and WAV integrity validation. Remaining: real model/runtime integration, measured latency/quality, explicit cancellation propagation and audio artifact delivery/playback.
3. **Durable voice-session backend — initial implementation complete:** principal-scoped session metadata, state transitions, cancellation and cursor-based event journal/API are implemented. Retention/deletion policy and end-to-end client integration remain.
4. **End-to-end voice turn:** microphone capture -> validated upload -> local ASR -> authenticated ORACLE conversation -> local TTS -> client playback.
5. **Streaming and interruption:** add VAD, partial transcription, chunked synthesis, reconnect and playback interruption only after phase 4 is stable.
6. **Advanced audio:** evaluate diarization, enhancement and multilingual quality independently, with explicit user consent and separate capability grants.

## Required verification

- Unit tests for codec/container signatures, spoofed MIME, malformed headers, truncation, duration and byte limits, transcript bounds and output validation.
- Worker isolation tests proving non-root UID, no network, read-only model mount, dropped capabilities, bounded memory/CPU/process count and enforced timeout.
- Model provenance tests for immutable revision, license metadata and checksum mismatch.
- Authorization tests for missing capability, expired/revoked credential, tenant/application/principal isolation and revocation between pipeline stages.
- State-machine tests for duplicate finalize, concurrent turns, interruption during transcription/synthesis/playback, late worker results and restart recovery.
- End-to-end tests using actual ASR and TTS containers and representative audio fixtures, including noisy speech, silence, clipped speech, multiple languages and unsupported codecs.
- Target-host tests for microphone permission UX, latency, playback interruption, audio device changes and resource usage.
- Release evidence must identify model revisions, fixtures, measured latency/quality and exact passing CI run. Mocked tests alone do not satisfy real-runtime acceptance.

## Current verified boundary

The repository contains audio metadata inspection, a separately provisioned offline faster-whisper ASR worker, and an offline Piper TTS worker with a capability-scoped synthesis API. TTS validates model revision/checksums and generated WAV digest/metadata, but has not been run with a real voice model on the target host. ASR remains unverified with a real installed model on the target host. Principal-scoped voice-session metadata, state transitions, cancellation and cursor-based event APIs are implemented as a backend foundation. Browser microphone capture, client playback, streaming VAD/turn-taking, retention/deletion workflows and end-to-end spoken conversation remain outstanding. These are explicit remaining tasks, not completed features.
