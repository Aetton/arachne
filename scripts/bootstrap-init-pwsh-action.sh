#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="${SOURCE_DIR:-$ROOT_DIR/hubs/forgejo/actions/init-pwsh}"

ACTION_REPO="${ACTION_REPO:-}"
ACTION_OWNER="${ACTION_OWNER:-arachne}"
ACTION_NAME="${ACTION_NAME:-init-pwsh}"
ACTION_BRANCH="${ACTION_BRANCH:-main}"
ACTION_TAG="${ACTION_TAG:-v1}"
COMMIT_MESSAGE="${COMMIT_MESSAGE:-Bootstrap Arachne init-pwsh action}"
FORCE_PUSH="${FORCE_PUSH:-false}"

BOOTSTRAP_CREATE_OWNER="${BOOTSTRAP_CREATE_OWNER:-true}"
BOOTSTRAP_CREATE_REPO="${BOOTSTRAP_CREATE_REPO:-false}"
FORGEJO_URL="${FORGEJO_URL:-}"
FORGEJO_TOKEN="${FORGEJO_TOKEN:-}"
FORGEJO_REPO_PRIVATE="${FORGEJO_REPO_PRIVATE:-true}"
FORGEJO_VERIFY_TLS="${FORGEJO_VERIFY_TLS:-true}"

usage() {
  cat <<'EOF'
Usage:
  make bootstrap-init-pwsh

Environment:
  ACTION_REPO             Target Forgejo git remote.
  ACTION_OWNER            Forgejo org/user owner for API repo creation. Default: arachne.
  ACTION_NAME             Action repository name. Default: init-pwsh.
  ACTION_BRANCH           Branch to push. Default: main.
  ACTION_TAG              Tag to create/update. Default: v1.
  SOURCE_DIR              Action source directory. Default: hubs/forgejo/actions/init-pwsh.
  FORCE_PUSH              Set true to force-push branch/tag. Default: false.

  BOOTSTRAP_CREATE_OWNER  Create missing Forgejo owner/org. Default: true.
  BOOTSTRAP_CREATE_REPO   Create the target repo through Forgejo API.
  FORGEJO_URL             Forgejo base URL, required when creating owner/repo.
  FORGEJO_TOKEN           Forgejo API token, required when creating owner/repo.
  FORGEJO_REPO_PRIVATE    Create private repo. Default: true.
  FORGEJO_VERIFY_TLS      Set false to pass curl -k for internal/self-signed TLS.
EOF
}

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: missing required command: $1" >&2
    exit 2
  }
}

curl_tls_args() {
  if [[ "$FORGEJO_VERIFY_TLS" == "false" ]]; then
    printf '%s\n' "-k"
  fi
}

api_get_owner_status() {
  local tls_args=()
  mapfile -t tls_args < <(curl_tls_args)

  curl "${tls_args[@]}" -sS \
    -o /tmp/arachne-bootstrap-owner.json \
    -w '%{http_code}' \
    -H "Authorization: token $FORGEJO_TOKEN" \
    "$FORGEJO_URL/api/v1/orgs/$ACTION_OWNER"
}

api_create_owner() {
  local tls_args=()
  mapfile -t tls_args < <(curl_tls_args)

  local body
  body="$(
    cat <<EOF
{
  "username": "$ACTION_OWNER",
  "full_name": "$ACTION_OWNER",
  "description": "Arachne action hubs"
}
EOF
  )"

  curl "${tls_args[@]}" -sS \
    -o /tmp/arachne-bootstrap-owner-create.json \
    -w '%{http_code}' \
    -X POST \
    -H "Authorization: token $FORGEJO_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$body" \
    "$FORGEJO_URL/api/v1/orgs"
}

api_get_repo_status() {
  local tls_args=()
  mapfile -t tls_args < <(curl_tls_args)

  curl "${tls_args[@]}" -sS \
    -o /tmp/arachne-bootstrap-repo.json \
    -w '%{http_code}' \
    -H "Authorization: token $FORGEJO_TOKEN" \
    "$FORGEJO_URL/api/v1/repos/$ACTION_OWNER/$ACTION_NAME"
}

api_create_repo() {
  local tls_args=()
  mapfile -t tls_args < <(curl_tls_args)

  local private_json="true"
  if [[ "$FORGEJO_REPO_PRIVATE" == "false" ]]; then
    private_json="false"
  fi

  local body
  body="$(
    cat <<EOF
{
  "name": "$ACTION_NAME",
  "private": $private_json,
  "auto_init": false,
  "description": "Arachne Forgejo action hub for PowerShell telemetry"
}
EOF
  )"

  curl "${tls_args[@]}" -sS \
    -o /tmp/arachne-bootstrap-create.json \
    -w '%{http_code}' \
    -X POST \
    -H "Authorization: token $FORGEJO_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$body" \
    "$FORGEJO_URL/api/v1/orgs/$ACTION_OWNER/repos"
}

ensure_api_settings() {
  need curl

  if [[ -z "$FORGEJO_URL" || -z "$FORGEJO_TOKEN" ]]; then
    echo "ERROR: FORGEJO_URL and FORGEJO_TOKEN are required when creating owner/repo" >&2
    exit 2
  fi

  FORGEJO_URL="${FORGEJO_URL%/}"
}

ensure_target_owner() {
  if [[ "$BOOTSTRAP_CREATE_OWNER" != "true" && "$BOOTSTRAP_CREATE_REPO" != "true" ]]; then
    return 0
  fi

  ensure_api_settings

  echo "→ checking Forgejo owner/org $ACTION_OWNER"
  local code
  code="$(api_get_owner_status)"

  case "$code" in
    200)
      echo "→ owner/org already exists: $ACTION_OWNER"
      ;;
    404)
      if [[ "$BOOTSTRAP_CREATE_OWNER" != "true" ]]; then
        echo "ERROR: owner/org $ACTION_OWNER does not exist and BOOTSTRAP_CREATE_OWNER=false" >&2
        exit 2
      fi
      echo "→ owner/org not found, creating: $ACTION_OWNER"
      code="$(api_create_owner)"
      case "$code" in
        201)
          echo "→ owner/org created: $ACTION_OWNER"
          ;;
        409|422)
          echo "→ owner/org create returned HTTP $code, assuming it already exists or was created concurrently"
          ;;
        *)
          echo "ERROR: owner/org create failed with HTTP $code" >&2
          cat /tmp/arachne-bootstrap-owner-create.json >&2 || true
          exit 2
          ;;
      esac
      ;;
    *)
      echo "ERROR: owner/org check failed with HTTP $code" >&2
      cat /tmp/arachne-bootstrap-owner.json >&2 || true
      exit 2
      ;;
  esac
}

ensure_target_repo() {
  if [[ "$BOOTSTRAP_CREATE_REPO" != "true" ]]; then
    return 0
  fi

  ensure_api_settings
  ensure_target_owner

  echo "→ checking Forgejo repo $ACTION_OWNER/$ACTION_NAME"
  local code
  code="$(api_get_repo_status)"

  case "$code" in
    200)
      echo "→ repo already exists: $ACTION_OWNER/$ACTION_NAME"
      return 0
      ;;
    404)
      echo "→ repo not found, creating: $ACTION_OWNER/$ACTION_NAME"
      ;;
    *)
      echo "ERROR: repo check failed with HTTP $code" >&2
      cat /tmp/arachne-bootstrap-repo.json >&2 || true
      exit 2
      ;;
  esac

  code="$(api_create_repo)"

  case "$code" in
    201)
      echo "→ repo created: $ACTION_OWNER/$ACTION_NAME"
      ;;
    409|422)
      echo "→ repo create returned HTTP $code, assuming it already exists or was created concurrently"
      ;;
    *)
      echo "ERROR: repo create failed with HTTP $code" >&2
      cat /tmp/arachne-bootstrap-create.json >&2 || true
      exit 2
      ;;
  esac
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

need git
need rsync

ensure_target_repo

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
  owner:  $ACTION_OWNER
  name:   $ACTION_NAME
  branch: $ACTION_BRANCH
  tag:    $ACTION_TAG

Workflow usage:

  - uses: $ACTION_OWNER/$ACTION_NAME@$ACTION_TAG
EOF
