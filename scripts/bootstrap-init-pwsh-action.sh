#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="${SOURCE_DIR:-$ROOT_DIR/hubs/forgejo/actions/init-pwsh}"
ACTION_REPO="${ACTION_REPO:-}"
ACTION_BRANCH="${ACTION_BRANCH:-main}"
ACTION_TAG="${ACTION_TAG:-v1}"
COMMIT_MESSAGE="${COMMIT_MESSAGE:-Bootstrap Arachne init-pwsh action}"
FORCE_PUSH="${FORCE_PUSH:-false}"

usage() {
  cat <<'EOF'
Usage:
  ACTION_REPO=ssh://git@git.redsoft.internal:2222/arachne/init-pwsh.git \
    make bootstrap-init-pwsh

Environment:
  ACTION_REPO      Target Forgejo git remote. Required.
  ACTION_BRANCH    Branch to push. Default: main.
  ACTION_TAG       Tag to create/update. Default: v1.
  SOURCE_DIR       Action source directory. Default: hubs/forgejo/actions/init-pwsh.
  FORCE_PUSH       Set true to force-push branch/tag. Default: false.

The target repository must already exist in Forgejo. This script mirrors only the
contents of the action directory, not the whole Arachne repository.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ -z "$ACTION_REPO" ]]; then
  echo "ERROR: ACTION_REPO is required" >&2
  usage >&2
  exit 2
fi

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "ERROR: source directory not found: $SOURCE_DIR" >&2
  exit 2
fi

for required in action.yml dist/main.js dist/post.js; do
  if [[ ! -f "$SOURCE_DIR/$required" ]]; then
    echo "ERROR: missing required action file: $SOURCE_DIR/$required" >&2
    exit 2
  fi
done

if grep -Rqi "placeholder" "$SOURCE_DIR/dist/post.js"; then
  cat >&2 <<EOF
ERROR: $SOURCE_DIR/dist/post.js still looks like a placeholder.
Replace it with the real post hook before publishing the action hub.
EOF
  exit 2
fi

WORKDIR="$(mktemp -d)"
cleanup() {
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

rsync -a --delete \
  --exclude '.git' \
  --exclude 'node_modules' \
  "$SOURCE_DIR/" "$WORKDIR/"

cd "$WORKDIR"
git init -q
git checkout -B "$ACTION_BRANCH" >/dev/null 2>&1 || git checkout -b "$ACTION_BRANCH"
git add .

if git diff --cached --quiet; then
  echo "ERROR: nothing to publish from $SOURCE_DIR" >&2
  exit 2
fi

git commit -m "$COMMIT_MESSAGE" >/dev/null
git remote add origin "$ACTION_REPO"

if [[ "$FORCE_PUSH" == "true" ]]; then
  git push -f origin "$ACTION_BRANCH"
  git tag -f "$ACTION_TAG"
  git push -f origin "$ACTION_TAG"
else
  git push origin "$ACTION_BRANCH"
  git tag "$ACTION_TAG"
  git push origin "$ACTION_TAG"
fi

cat <<EOF
Arachne init-pwsh action published.

  repo:   $ACTION_REPO
  branch: $ACTION_BRANCH
  tag:    $ACTION_TAG

Workflow usage:

  - uses: arachne/init-pwsh@$ACTION_TAG
EOF
