#!/bin/bash
# Build and deploy the Traefik Compose stack using repository configuration.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ "`uname`" == "Darwin" ]; then
  DOCKER="/usr/local/bin/docker"
else
  DOCKER="docker"
fi

$DOCKER compose --env-file "$REPO_ROOT/.env" -f "$REPO_ROOT/docker/docker-compose.traefik.yaml" "$@"