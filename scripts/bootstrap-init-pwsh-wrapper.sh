#!/usr/bin/env bash
set -euo pipefail

cd /app

ACTION_OWNER="${ACTION_OWNER:-arachne}"
ACTION_NAME="${ACTION_NAME:-init-pwsh}"
ACTION_TAG="${ACTION_TAG:-v1}"
ACTION_BRANCH="${ACTION_BRANCH:-main}"
FORGEJO_SSH_USER="${FORGEJO_SSH_USER:-git}"
FORGEJO_SSH_PORT="${FORGEJO_SSH_PORT:-2222}"
BOOTSTRAP_CREATE_REPO="${BOOTSTRAP_CREATE_REPO:-true}"
FORGEJO_REPO_PRIVATE="${FORGEJO_REPO_PRIVATE:-false}"
FORGEJO_VERIFY_TLS="${FORGEJO_VERIFY_TLS:-false}"

export ACTION_OWNER ACTION_NAME ACTION_TAG ACTION_BRANCH
export FORGEJO_SSH_USER FORGEJO_SSH_PORT
export BOOTSTRAP_CREATE_REPO FORGEJO_REPO_PRIVATE FORGEJO_VERIFY_TLS

if [[ -z "${ACTION_REPO:-}" ]]; then
  base="${FORGEJO_SSH_HOST:-${FORGEJO_URL#http://}}"
  base="${base#https://}"
  base="${base%%/*}"
  base="${base%%:*}"

  if [[ -z "$base" ]]; then
    echo "ERROR: FORGEJO_URL or FORGEJO_SSH_HOST is required to derive ACTION_REPO" >&2
    exit 2
  fi

  export ACTION_REPO="ssh://${FORGEJO_SSH_USER}@${base}:${FORGEJO_SSH_PORT}/${ACTION_OWNER}/${ACTION_NAME}.git"
fi

echo "→ action remote: $ACTION_REPO"
exec /app/scripts/bootstrap-init-pwsh-action.sh
