# Arachne — operator commands. Works the same on your laptop and on the host.
#
#   make up        — bring Arachne up (SQLite, in-memory bus); creates .env/data if missing
#   make update    — pull latest code + rebuild + restart (the fast iteration loop)
#   make logs      — tail logs
#   make down      — stop
#   make ps        — status
#   make shell     — shell inside the running container
#   make rebuild   — force a clean image rebuild
#   make up-pg     — + Postgres
#   make up-nats   — + NATS  (also flips BUS_BACKEND for you)
#   make up-full   — + Postgres + NATS
#   make bootstrap-init-pwsh
#   make bootstrap-init-pwsh-local
#   make bootstrap-init-bash
#   make bootstrap-init-bash-local
#   make reset     — DANGER: stop and wipe the SQLite db + volumes
#
# Override the compose command if needed:  make up DC="docker-compose"

DC ?= docker compose
SERVICE ?= arachne

ACTION_OWNER ?= arachne
ACTION_NAME ?= init-pwsh
ACTION_TAG ?= v1
ACTION_BRANCH ?= main
FORGEJO_SSH_USER ?= git
FORGEJO_SSH_PORT ?= 2222
BOOTSTRAP_CREATE_REPO ?= true
FORGEJO_REPO_PRIVATE ?= false
FORGEJO_VERIFY_TLS ?= false

# Optional knobs for scripts/bootstrap-init-*-wrapper.sh.
# FORGEJO_URL and FORGEJO_TOKEN are expected to already exist in the container env.
BOOTSTRAP_ENV = \
	ACTION_REPO='$(ACTION_REPO)' \
	ACTION_OWNER='$(ACTION_OWNER)' \
	ACTION_NAME='$(ACTION_NAME)' \
	ACTION_BRANCH='$(ACTION_BRANCH)' \
	ACTION_TAG='$(ACTION_TAG)' \
	SOURCE_DIR='$(SOURCE_DIR)' \
	FORCE_PUSH='$(FORCE_PUSH)' \
	BOOTSTRAP_CREATE_REPO='$(BOOTSTRAP_CREATE_REPO)' \
	FORGEJO_REPO_PRIVATE='$(FORGEJO_REPO_PRIVATE)' \
	FORGEJO_VERIFY_TLS='$(FORGEJO_VERIFY_TLS)' \
	FORGEJO_SSH_USER='$(FORGEJO_SSH_USER)' \
	FORGEJO_SSH_PORT='$(FORGEJO_SSH_PORT)'

# ---- guards -------------------------------------------------------------
# .env must exist; data/ must exist before the volume mounts (else Docker
# creates it as root and the container can't write the SQLite file).
.PHONY: _preflight
_preflight:
	@test -f .env || (cp .env.example .env && echo "→ created .env from .env.example — edit runtime settings before production")
	@mkdir -p data

# ---- core lifecycle -----------------------------------------------------
.PHONY: up
up: _preflight
	$(DC) up -d --build
	@echo "→ Arachne: http://localhost:8080"
	@echo "→ Wiki:    http://localhost:8080/wiki/"
	@echo "→ API:     http://localhost:8080/docs"

.PHONY: down
down:
	$(DC) down

.PHONY: ps
ps:
	$(DC) ps

.PHONY: logs
logs:
	$(DC) logs -f --tail=100 $(SERVICE)

.PHONY: shell
shell:
	$(DC) exec $(SERVICE) bash

# ---- the iteration loop -------------------------------------------------
# Pull latest code (if this is a git checkout), rebuild image, restart.
.PHONY: update
update: _preflight
	@git rev-parse --is-inside-work-tree >/dev/null 2>&1 && git pull --ff-only || echo "→ not a git checkout, skipping pull"
	$(DC) up -d --build
	@echo "→ updated; wiki: http://localhost:8080/wiki/; logs: make logs"

.PHONY: rebuild
rebuild: _preflight
	$(DC) build --no-cache
	$(DC) up -d

.PHONY: restart
restart:
	$(DC) restart $(SERVICE)

# ---- profiles -----------------------------------------------------------
.PHONY: up-pg
up-pg: _preflight
	$(DC) --profile pg up -d --build

.PHONY: up-nats
up-nats: _preflight
	@grep -q '^BUS_BACKEND=nats' .env || (sed -i.bak 's/^BUS_BACKEND=.*/BUS_BACKEND=nats/' .env 2>/dev/null || echo "BUS_BACKEND=nats" >> .env)
	$(DC) --profile nats up -d --build
	@echo "→ BUS_BACKEND set to nats in .env"

.PHONY: up-full
up-full: _preflight
	@grep -q '^BUS_BACKEND=nats' .env || (sed -i.bak 's/^BUS_BACKEND=.*/BUS_BACKEND=nats/' .env 2>/dev/null || echo "BUS_BACKEND=nats" >> .env)
	$(DC) --profile pg --profile nats up -d --build

# ---- hub bootstrap ------------------------------------------------------
.PHONY: bootstrap-init-pwsh
bootstrap-init-pwsh:
	@$(DC) exec -T $(SERVICE) bash -lc "$(BOOTSTRAP_ENV) bash /app/scripts/bootstrap-init-pwsh-http.sh"

.PHONY: bootstrap-init-pwsh-local
bootstrap-init-pwsh-local:
	@bash scripts/bootstrap-init-pwsh-action.sh

.PHONY: bootstrap-init-bash
bootstrap-init-bash:
	@$(DC) exec -T $(SERVICE) bash -lc "$(BOOTSTRAP_ENV) ACTION_NAME='init-bash' bash /app/scripts/bootstrap-init-bash-http.sh"

.PHONY: bootstrap-init-bash-local
bootstrap-init-bash-local:
	@ACTION_NAME='init-bash' bash scripts/bootstrap-init-bash-action.sh

# ---- maintenance --------------------------------------------------------
.PHONY: reset
reset:
	@printf "This stops Arachne and DELETES the SQLite db + volumes. Type yes: " && read ans && [ "$$ans" = "yes" ]
	$(DC) down -v
	rm -f data/arachne.db
	@echo "→ wiped. 'make up' starts fresh."

.PHONY: config
config:
	$(DC) config

.PHONY: help
help:
	@grep -E '^#   make' Makefile | sed 's/^#   /  /'

.DEFAULT_GOAL := help
