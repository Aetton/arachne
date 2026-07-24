FROM node:22-alpine AS docs-builder

WORKDIR /docs
COPY docs/package*.json ./
RUN npm ci
COPY docs/ ./
ENV DOCS_BASE=/wiki/
RUN npm run docs:build

FROM python:3.12-slim

# ansible + openssh-client for playbooks that provision/deploy over SSH.
# git/rsync are needed by hub bootstrap tasks that publish reusable Forgejo actions.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ansible openssh-client curl ca-certificates bash git rsync \
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
COPY hubs/ ./hubs/
COPY scripts/ ./scripts/
COPY --from=docs-builder /docs/.vitepress/dist /app/wiki/

RUN chmod +x api/runners/demo_play.sh \
    && chmod +x scripts/*.sh

WORKDIR /app/api

ENV PYTHONUNBUFFERED=1 \
    DATABASE_URL=postgresql+psycopg://arachne:arachne@db:5432/arachne \
    ANSIBLE_PLAYBOOKS_DIR=/app/playbooks \
    SCENARIOS_CONFIG=/app/config/scenarios.yaml

EXPOSE 8000

CMD ["sh", "-c", "alembic -c ../alembic.ini upgrade head && exec uvicorn main:app --host 0.0.0.0 --port 8000"]
