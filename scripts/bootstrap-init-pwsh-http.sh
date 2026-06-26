#!/usr/bin/env bash
set -euo pipefail

cd /app

ACTION_OWNER="${ACTION_OWNER:-arachne}"
ACTION_NAME="${ACTION_NAME:-init-pwsh}"
ACTION_TAG="${ACTION_TAG:-v1}"
ACTION_BRANCH="${ACTION_BRANCH:-main}"
BOOTSTRAP_CREATE_REPO="${BOOTSTRAP_CREATE_REPO:-true}"
FORGEJO_REPO_PRIVATE="${FORGEJO_REPO_PRIVATE:-false}"
FORGEJO_VERIFY_TLS="${FORGEJO_VERIFY_TLS:-false}"
FORGEJO_GIT_USER="${FORGEJO_GIT_USER:-${ACTION_OWNER}-bot}"

export ACTION_OWNER ACTION_NAME ACTION_TAG ACTION_BRANCH
export BOOTSTRAP_CREATE_REPO FORGEJO_REPO_PRIVATE FORGEJO_VERIFY_TLS FORGEJO_GIT_USER

if [[ -z "${ACTION_REPO:-}" ]]; then
  host="${FORGEJO_URL:-}"
  host="${host#http://}"
  host="${host#https://}"
  host="${host%%/*}"

  if [[ -z "$host" ]]; then
    echo "ERROR: FORGEJO_URL is required" >&2
    exit 2
  fi

  export ACTION_REPO="https://${host}/${ACTION_OWNER}/${ACTION_NAME}.git"
fi

echo "→ action remote: $ACTION_REPO"
exec /app/scripts/bootstrap-init-pwsh-action.sh
