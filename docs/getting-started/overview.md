# Overview

Arachne is a lightweight orchestration portal for CI/CD workflows and infrastructure automation.
An operator selects a scenario, fills its parameters, and runs it. Arachne validates access,
dispatches the configured steps through driver plugins, streams logs, and collects artifact links.

## Core concepts

- **Scenario** — a versioned workflow definition.
- **Component** — a reusable scenario building block.
- **Driver** — an adapter for an execution backend.
- **Trigger** — a manual, scheduled, or chained start condition.
- **Bus** — transports requests and responses between the portal and workers.
