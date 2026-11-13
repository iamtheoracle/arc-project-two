#!/usr/bin/env bash
set -euo pipefail
image="${ORACLE_ARC_TTS_WORKER_IMAGE:-oracle-arc-tts-worker:local}"
podman build --pull=always -f Dockerfile.orbits-tts-worker -t "$image" .
echo "Built offline Piper TTS worker image: $image"
echo "Provision a pinned model separately; see docs/LOCAL_TTS_MODEL_SETUP.md."
