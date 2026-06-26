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
COPY frontend/ ./frontend/
COPY config/ ./config/
COPY playbooks/ ./playbooks/
COPY hubs/ ./hubs/
COPY scripts/ ./scripts/

RUN chmod +x api/runners/demo_play.sh \
    && chmod +x scripts/*.sh

WORKDIR /app/api

ENV PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:///./data/arachne.db \
    ANSIBLE_PLAYBOOKS_DIR=/app/playbooks \
    SCENARIOS_CONFIG=/app/config/scenarios.yaml

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
