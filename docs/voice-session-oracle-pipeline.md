# ORACLE voice turn pipeline

The application-credential voice flow is deliberately split into bounded, auditable stages:

1. Create a principal-scoped session with `audio.capture`.
2. Upload a validated audio asset to `POST /v1/platform/audio/sessions/{session_id}/transcribe`.
   The endpoint requires `audio.transcribe` and `orbits.process`, scans the asset through the fail-closed quarantine scanner, and invokes the installed offline `audio.transcribe` processor. Clean transient bytes are deleted immediately after inference. Scanner failures never reach ASR.
3. Send the returned transcript to `POST /v1/platform/audio/sessions/{session_id}/respond`.
   This requires `agent.execute` and queues an ordinary ORACLE platform execution. It does not call a model directly from the API process. The worker rechecks the current agent, route, principal grants, quotas, model-region policy, tool grants and execution lease.
4. Poll `GET /v1/platform/executions/{execution_id}` until the execution is `succeeded`. A queued, running, failed, cancelled or dead-lettered execution cannot be spoken.
5. Call `POST /v1/platform/audio/sessions/{session_id}/speak` with the execution ID. The endpoint requires `agent.execution.read` and `audio.synthesize`, reloads the execution inside the authenticated principal scope, and sends only the validated final response text to the isolated local TTS runtime.
6. The local speech result is returned ephemerally. The API does not persist the transcript, model response or generated audio in the voice session journal. Clients acknowledge playback through `POST /v1/platform/audio/sessions/{session_id}/playback` with `started`, `completed` or `interrupted`.

## Capability set

A full spoken turn needs the separately granted capabilities `audio.capture`, `audio.read`, `audio.transcribe`, `orbits.process`, `agent.execute`, `agent.execution.read` and `audio.synthesize`. Cancellation remains separately controlled by `audio.cancel` and `agent.execution.cancel`.

## Operational requirements and limits

- ASR and TTS are local-only; no cloud fallback is implemented.
- The target host must separately provision and verify compatible ASR and TTS model assets and their reviewed manifests.
- ClamAV must be available; scanner failure is fail-closed.
- The normal ORACLE worker must be running and the selected agent version/model route/quota must be configured.
- A successful API response is not evidence of human-quality speech. Measure latency, intelligibility, pronunciation, interruption handling and audio output quality on the target device before making quality claims.
- Browser microphone capture, streaming partial ASR, VAD/barge-in, playback UX and automatic hands-free turn orchestration remain client integration work.
