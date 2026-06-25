# Arachne Hubs

A hub is a utility belt for a spider.

Arachne core owns scenarios, runs, threads, status and UI. A spider owns backend-specific execution. A hub owns the small reusable helpers that make an external runtime speak Arachne's thread protocol without copying callback code into every pipeline.

Examples:

```text
forgejo hub  -> Forgejo Actions
ansible hub  -> callback plugins
shell hub    -> shell wrappers
opentofu hub -> tofu wrappers
```

The core must not require a hub to exist. Hubs are optional adapters for better telemetry and less YAML plumbing.

## Current hub

```text
hubs/forgejo/actions/init-pwsh
```

This is the first MVP action for Windows PowerShell workflows in Forgejo Actions.
