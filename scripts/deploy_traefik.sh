#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

docker compose --env-file "$REPO_ROOT/.env" -f "$REPO_ROOT/docker/docker_compose.traefik.yaml" "$@"