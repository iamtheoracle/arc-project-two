# Local ORBITS speech-to-text setup

Speech recognition is a separate, opt-in local capability. It is not bundled into the
metadata inspector and does not use a remote inference service.

## Model provisioning

1. Choose and review a faster-whisper-compatible model.
2. Download its complete model snapshot on a trusted provisioning machine.
3. Record the exact model repository, immutable revision, download provenance and SHA-256
   manifest in your deployment inventory.
4. Transfer the model directory to the target host through your approved artifact process.
5. Mount that directory read-only as `/models/active` in the ASR worker.

The runtime deliberately does not download or resolve a model name. It requires local
`config.json` and `model.bin`, sets `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1`, runs Podman with `--network=none`, and fails closed if the
model directory or worker image is missing.

## Provision a pinned model snapshot

Install the provisioning-only dependency on a trusted host (not in the worker):

```bash
python -m pip install -r requirements-asr-provision.txt
export ORACLE_ARC_ASR_MODEL_ID=Systran/faster-whisper-small
export ORACLE_ARC_ASR_MODEL_REVISION=<immutable-hugging-face-commit>
export ORACLE_ARC_ASR_MODEL_DIR=/opt/oracle-arc/models/whisper-small
python scripts/install-asr-model.py
```

Use a reviewed immutable commit hash, not a floating branch or tag. The installer writes
a SHA-256 manifest. Review the model's license and provenance before provisioning.

## Build and configure

```bash
bash scripts/build-orbits-asr-worker.sh
export ORACLE_ARC_ASR_WORKER_IMAGE=oracle-arc-asr-worker:local
export ORACLE_ARC_ASR_MODEL_DIR=/opt/oracle-arc/models/whisper-small
```

The host model directory must be absolute and readable by the container's unprivileged
UID 65534. Do not make it writable by the worker.

## Limits and current verification boundary

The worker accepts at most 25 MB of audio, has a 300-second wall-clock deadline,
uses CPU int8 inference, caps transcript output at 100 KB and returns a local-inference
marker. A missing or malformed model is an error, never a reason to route audio remotely.

The worker implementation is present, but real model inference is not considered verified
until the exact approved model is installed on the target host and the isolated container
integration test is recorded as passing. Model license, revision and checksum must be
reviewed before deployment.
