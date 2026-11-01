#!/usr/bin/env bash
set -euo pipefail
image="${ORACLE_ARC_ORBITS_WORKER_IMAGE:-oracle-arc-orbits-worker:local}"
podman build --pull=always -f Dockerfile.orbits-worker -t "$image" .
echo "Built isolated ORBITS worker image: $image"
