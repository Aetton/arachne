# Forgejo actions

Reusable Arachne utility-belt actions for Forgejo workflows.

## Actions

```text
init-bash/
init-pwsh/    # copied from the old init-pwsh repository during export
```

## Manual runs

When a workflow is started manually from Forgejo UI, Arachne service inputs are empty.

In that mode actions must behave as noop and let the workflow run normally.

## Arachne runs

When Arachne dispatches a workflow, it injects:

```text
build_id
arachne_callback
arachne_token
```

The action reads these values, mirrors logs, and closes the Arachne thread from the post hook.
