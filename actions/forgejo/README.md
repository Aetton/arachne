# Forgejo actions

Legacy callback actions for Forgejo workflows. The current Forgejo v16 spider does
not require them: it polls runs, logs and artifacts through Forgejo API.

## Actions

```text
init-bash/
init-pwsh/
```

## Manual runs

When a workflow is started manually from Forgejo UI, Arachne service inputs are empty.

In that mode actions must behave as noop and let the workflow run normally.

## Legacy callback runs

Old Arachne versions injected:

```text
build_id
arachne_callback
arachne_token
```

The action reads these values, mirrors logs, and closes the old switchboard thread.
With the current spider the inputs are empty unless a caller supplies them explicitly,
so the action behaves as noop.
