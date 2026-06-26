#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  *Username*)
    printf '%s\n' "${FORGEJO_GIT_USER:-arachne-bot}"
    ;;
  *Password*)
    printf '%s\n' "${FORGEJO_GIT_PASSWORD:-}"
    ;;
  *)
    printf '\n'
    ;;
esac
