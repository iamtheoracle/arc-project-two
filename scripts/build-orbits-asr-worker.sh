#!/usr/bin/env bash
set -euo pipefail
image="${ORACLE_ARC_ASR_WORKER_IMAGE:-oracle-arc-asr-worker:local}"
podman build --pull=always -f Dockerfile.orbits-asr-worker -t "$image" .
echo "Built offline ASR worker image: $image"
echo "Mount a separately installed model with ORACLE_ARC_ASR_MODEL_DIR before enabling transcription."
