#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export ACTION_NAME="${ACTION_NAME:-init-bash}"
export SOURCE_DIR="${SOURCE_DIR:-$ROOT_DIR/hubs/forgejo/actions/init-bash}"
export COMMIT_MESSAGE="${COMMIT_MESSAGE:-Bootstrap Arachne init-bash action}"

exec "$ROOT_DIR/scripts/bootstrap-init-pwsh-action.sh" "$@"
