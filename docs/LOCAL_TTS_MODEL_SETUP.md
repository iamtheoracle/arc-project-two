# Local TTS model setup

Oracle Arc's local speech synthesis worker uses Piper and a separately provisioned ONNX voice. Model installation is an explicit administrative operation; request-time inference never downloads a model.

## 1. Verify model provenance first

Choose a Piper-compatible ONNX voice from a source you trust. Review the upstream repository's model card, license, permitted use, language, voice identity and sample quality. Do not assume all community voices share the same license. The installer requires the exact upstream license identifier as an explicit operator assertion; it does not independently validate legal rights.

Obtain the immutable 40-character repository commit SHA and the exact ONNX model and JSON config filenames from that same revision.

## 2. Provision the model

Install the provisioning dependency in a dedicated administrative environment:

```bash
python -m pip install -r requirements-tts-provision.txt
export ORACLE_ARC_TTS_MODEL_ID='YOUR_REVIEWED_REPOSITORY'
export ORACLE_ARC_TTS_MODEL_REVISION='40_CHARACTER_COMMIT_SHA'
export ORACLE_ARC_TTS_MODEL_FILE='YOUR_VOICE.onnx'
export ORACLE_ARC_TTS_CONFIG_FILE='YOUR_VOICE.onnx.json'
export ORACLE_ARC_TTS_MODEL_LICENSE='UPSTREAM_LICENSE_IDENTIFIER'
export ORACLE_ARC_TTS_MODEL_DIR='/opt/oracle-arc/models/piper-voice'
python scripts/install-tts-model.py
```

The installer copies only the selected model/config pair and records SHA-256 digests, repository, revision and declared license. Treat the manifest as integrity/provenance metadata, not a substitute for reviewing the license.

## 3. Build and configure the worker

```bash
bash scripts/build-orbits-tts-worker.sh
export ORACLE_ARC_TTS_MODEL_DIR='/opt/oracle-arc/models/piper-voice'
export ORACLE_ARC_TTS_WORKER_IMAGE='oracle-arc-tts-worker:local'
```

The API runner mounts the model read-only into a non-root worker with no network, a read-only root filesystem, dropped capabilities, resource limits and a hard timeout. It uses `--pull=never`; a missing image fails closed.

## Current boundary

The worker currently exposes one reviewed catalogue key, `local-default`, to avoid accepting arbitrary model paths or caller-selected voices. This is an engine foundation, not a complete user-facing voice feature: durable voice sessions, authorization-aware TTS API routes, client playback, microphone capture and streaming turn-taking remain separate implementation work. Do not expose the worker directly to browsers.
