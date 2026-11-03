# Arachne operator tasks. Run 'just' to see all available recipes.
# Overrides: DC="docker-compose" SERVICE="arachne" just logs
set shell := ["bash", "-euo", "pipefail", "-c"]

dc := env_var_or_default("DC", "docker compose")
service := env_var_or_default("SERVICE", "arachne")

action_repo := env_var_or_default("ACTION_REPO", "")
action_owner := env_var_or_default("ACTION_OWNER", "arachne")
action_name := env_var_or_default("ACTION_NAME", "init-pwsh")
action_branch := env_var_or_default("ACTION_BRANCH", "main")
action_tag := env_var_or_default("ACTION_TAG", "v1")
source_dir := env_var_or_default("SOURCE_DIR", "")
force_push := env_var_or_default("FORCE_PUSH", "false")
create_repo := env_var_or_default("BOOTSTRAP_CREATE_REPO", "true")
repo_private := env_var_or_default("FORGEJO_REPO_PRIVATE", "false")
verify_tls := env_var_or_default("FORGEJO_VERIFY_TLS", "false")
ssh_user := env_var_or_default("FORGEJO_SSH_USER", "git")
ssh_port := env_var_or_default("FORGEJO_SSH_PORT", "2222")

# List operator commands
default:
    @just --list

# Prepare .env and writable SQLite data directory
_preflight:
    @if [[ ! -f .env ]]; then cp .env.example .env; echo "→ created .env from .env.example — edit runtime settings before production"; fi
    @mkdir -p data

# Start Arachne
up: _preflight
    {{dc}} up -d --build
    @echo "→ Arachne: http://localhost:8080"
    @echo "→ Wiki:    http://localhost:8080/wiki/"
    @echo "→ API:     http://localhost:8080/docs"

# Stop containers
down:
    {{dc}} down

# Show containers
ps:
    {{dc}} ps

# Follow service logs
logs:
    {{dc}} logs -f --tail=100 {{service}}

# Open a shell in the service container
shell:
    {{dc}} exec {{service}} bash

# Pull latest code, rebuild and restart
update: _preflight
    @if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then git pull --ff-only; else echo "→ not a git checkout, skipping pull"; fi
    {{dc}} up -d --build
    @echo "→ updated; wiki: http://localhost:8080/wiki/; logs: just logs"

# Rebuild image without cached layers
rebuild: _preflight
    {{dc}} build --no-cache
    {{dc}} up -d

# Restart the application service
restart:
    {{dc}} restart {{service}}

# Start Arachne with PostgreSQL
up-pg: _preflight
    {{dc}} --profile pg up -d --build

# Set BUS_BACKEND=nats in .env, without duplicate entries
_set-nats:
    @if grep -q '^BUS_BACKEND=' .env; then sed -i.bak 's/^BUS_BACKEND=.*/BUS_BACKEND=nats/' .env; else printf '\nBUS_BACKEND=nats\n' >> .env; fi

# Start Arachne with NATS
up-nats: _preflight _set-nats
    {{dc}} --profile nats up -d --build
    @echo "→ BUS_BACKEND set to nats in .env"

# Start Arachne with PostgreSQL and NATS
up-full: _preflight _set-nats
    {{dc}} --profile pg --profile nats up -d --build

# Bootstrap init-pwsh action inside the container
bootstrap-init-pwsh:
    {{dc}} exec -T \
      -e ACTION_REPO="{{action_repo}}" -e ACTION_OWNER="{{action_owner}}" \
      -e ACTION_NAME="{{action_name}}" -e ACTION_BRANCH="{{action_branch}}" -e ACTION_TAG="{{action_tag}}" \
      -e SOURCE_DIR="{{source_dir}}" -e FORCE_PUSH="{{force_push}}" \
      -e BOOTSTRAP_CREATE_REPO="{{create_repo}}" -e FORGEJO_REPO_PRIVATE="{{repo_private}}" \
      -e FORGEJO_VERIFY_TLS="{{verify_tls}}" -e FORGEJO_SSH_USER="{{ssh_user}}" \
      -e FORGEJO_SSH_PORT="{{ssh_port}}" \
      {{service}} bash /app/scripts/bootstrap-init-pwsh-http.sh

# Bootstrap init-pwsh action on the host
bootstrap-init-pwsh-local:
    bash scripts/bootstrap-init-pwsh-action.sh

# Bootstrap init-bash action inside the container
bootstrap-init-bash:
    {{dc}} exec -T \
      -e ACTION_REPO="{{action_repo}}" -e ACTION_OWNER="{{action_owner}}" \
      -e ACTION_NAME=init-bash -e ACTION_BRANCH="{{action_branch}}" -e ACTION_TAG="{{action_tag}}" \
      -e SOURCE_DIR="{{source_dir}}" -e FORCE_PUSH="{{force_push}}" \
      -e BOOTSTRAP_CREATE_REPO="{{create_repo}}" -e FORGEJO_REPO_PRIVATE="{{repo_private}}" \
      -e FORGEJO_VERIFY_TLS="{{verify_tls}}" -e FORGEJO_SSH_USER="{{ssh_user}}" \
      -e FORGEJO_SSH_PORT="{{ssh_port}}" \
      {{service}} bash /app/scripts/bootstrap-init-bash-http.sh

# Bootstrap init-bash action on the host
bootstrap-init-bash-local:
    ACTION_NAME=init-bash bash scripts/bootstrap-init-bash-action.sh

# Destructive: remove SQLite DB and Compose volumes
reset:
    @read -r -p "This stops Arachne and DELETES the SQLite db + volumes. Type yes: " answer; [[ "$answer" == "yes" ]]
    {{dc}} down -v
    rm -f data/arachne.db
    @echo "→ wiped. 'just up' starts fresh."

# Show resolved Compose configuration
config:
    {{dc}} config

# List available recipes
help:
    @just --list
