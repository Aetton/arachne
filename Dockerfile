FROM node:22-alpine AS docs-builder

WORKDIR /docs
COPY docs/package*.json ./
RUN npm ci
COPY docs/ ./
ENV DOCS_BASE=/wiki/ \
    DOCS_LAST_UPDATED=false
RUN npm run docs:build

FROM python:3.12-slim-bookworm

ARG TOFU_VERSION=1.12.6

# ansible + openssh-client for playbooks that provision/deploy over SSH.
# sshpass enables password-backed SSH credentials from Control -> Secrets.
# git/rsync are needed by hub bootstrap tasks that publish reusable Forgejo actions.
# Pin the Debian release and use the reachable mirror instead of deb.debian.org.
RUN sed -i \
        -e 's|http://deb.debian.org/debian|https://mirror.yandex.ru/debian|g' \
        -e 's|http://deb.debian.org/debian-security|https://mirror.yandex.ru/debian-security|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ansible openssh-client sshpass curl ca-certificates bash git rsync \
    && arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
         amd64) tofu_arch=amd64 ;; \
         arm64) tofu_arch=arm64 ;; \
         *) echo "unsupported architecture for OpenTofu: $arch" >&2; exit 1 ;; \
       esac \
    && curl -fsSLo /tmp/tofu.deb \
        "https://github.com/opentofu/opentofu/releases/download/v${TOFU_VERSION}/tofu_${TOFU_VERSION}_${tofu_arch}.deb" \
    && apt-get install -y --no-install-recommends /tmp/tofu.deb \
    && tofu version \
    && rm -f /tmp/tofu.deb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ ./api/
COPY alembic.ini ./alembic.ini
COPY migrations/ ./migrations/
COPY frontend/ ./frontend/
COPY config/ ./config/
COPY playbooks/ ./playbooks/
COPY tofu/ ./tofu/
COPY hubs/ ./hubs/
COPY scripts/ ./scripts/
COPY --from=docs-builder /docs/.vitepress/dist /app/wiki/

RUN chmod +x api/runners/demo_play.sh \
    && chmod +x scripts/*.sh \
    && mkdir -p /var/lib/arachne/tofu-state \
    && mkdir -p /usr/local/share/ca-certificates/arachne

WORKDIR /app/api

ENV PYTHONUNBUFFERED=1 \
    DATABASE_URL=postgresql+psycopg://arachne:arachne@db:5432/arachne \
    ANSIBLE_PLAYBOOKS_DIR=/app/playbooks \
    SCENARIOS_CONFIG=/app/config/scenarios.yaml \
    TOFU_ROOT=/app/tofu \
    TOFU_STATE_ROOT=/var/lib/arachne/tofu-state \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

EXPOSE 8000

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["sh", "-c", "alembic -c ../alembic.ini upgrade head && exec uvicorn main:app --host 0.0.0.0 --port 8000"]
