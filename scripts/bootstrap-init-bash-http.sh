#!/usr/bin/env bash
set -euo pipefail

export ACTION_NAME="${ACTION_NAME:-init-bash}"
export COMMIT_MESSAGE="${COMMIT_MESSAGE:-Bootstrap Arachne init-bash action}"

exec /app/scripts/bootstrap-init-pwsh-http.sh "$@"
