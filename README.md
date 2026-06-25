# Arachne

Arachne is a lightweight orchestration portal for CI/CD workflows,
infrastructure automation, live logs, and artifact links.

Operators choose a scenario, press **Run**, and Arachne dispatches the configured
thread through a driver plugin: Forgejo/Gitea-compatible workflow, Ansible
playbook, OpenTofu module, or another backend.

Arachne is intended to be a generic open-source framework. Environment-specific
behavior belongs in local scenario files and runtime configuration, not in the
core code.

## Features

- Scenario-driven orchestration from YAML.
- Driver plugin model for build, provision, and deploy backends.
- Live log streaming through the Arachne UI.
- Artifact link collection.
- Local users, roles, teams, and scenario visibility.
- SQLite by default, PostgreSQL profile available.
- In-memory bus by default, NATS profile available.

## Quick start

```bash
cp .env.example .env
make up
make logs
```

Open the portal on:

```text
http://localhost:8080
```

Use the seeded `admin` user with the password configured in `.env`.

## Common commands

```bash
make up        # start Arachne
make update    # pull, rebuild, restart
make logs      # follow portal logs
make restart   # restart portal only
make down      # stop containers
make ps        # show containers
```

## Configuration

Copy `.env.example` to `.env` and replace placeholder values with values for
your environment.

Public examples use placeholder hosts such as:

```text
forgejo.example.internal
nexus.example.internal
arachne.example.internal
```

Real deployments should keep local values in `.env` or ignored local scenario
files.

## Scenario model

Scenarios live in `config/scenarios.yaml` and describe:

- form parameters;
- manual, schedule, or chain triggers;
- ordered steps;
- driver name;
- backend-specific inputs.

Environment-specific scenarios can be kept in ignored local files. The core
should remain generic.

## Extension model

- Add a scenario by editing scenario YAML.
- Add a build or provision backend by implementing a spider plugin.
- Add a trigger by implementing a trigger plugin.
- Add a bus backend by implementing the bus contract.
- Add a theme by extending the frontend theme CSS.

## Repository structure

```text
api/                  FastAPI app, orchestration core, plugins
frontend/             templates and static assets
config/               scenario examples
playbooks/            Ansible and workflow callback examples
tofu/                 OpenTofu examples
docker-compose.yml    local runtime profiles
Makefile              operator commands
```

## Production notes

Before real users touch the portal:

- replace all placeholder values in `.env`;
- use a long random session signing value;
- change the initial admin password after first login;
- use a dedicated service account for CI backend access;
- make sure runners can reach `ARACHNE_URL`;
- keep TLS verification enabled and mount your internal CA when needed;
- keep local deployment files out of git.

## License

Arachne is licensed under the Apache License, Version 2.0. See `LICENSE` and
`NOTICE`.
