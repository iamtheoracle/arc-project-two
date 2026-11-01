#!/usr/bin/env sh
set -eu

IMAGE="${ORACLE_ARC_PLUGIN_WORKER_IMAGE:-oracle-arc-plugin-worker:local}"
case "$IMAGE" in
  *[[:space:]]*|"")
    echo "Invalid plugin worker image reference" >&2
    exit 2
    ;;
esac

podman build --pull=always --file Dockerfile.plugin-worker --tag "$IMAGE" .
podman image inspect "$IMAGE" --format '{{.Id}}'
echo "Built isolated plugin worker image: $IMAGE"
