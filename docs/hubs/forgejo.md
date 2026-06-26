# Arachne Forgejo Hub

Forgejo public API can dispatch workflows and return run metadata, but current Forgejo API documentation does not expose runner log download endpoints. Arachne therefore treats Forgejo as the execution backend and uses hub actions for workflow-side telemetry.

## Goal

A Forgejo workflow should need only one Arachne line:

```yaml
- uses: arachne/init-pwsh@v1
```

After that, ordinary PowerShell steps should keep working normally while their output is mirrored back into the Arachne thread.

## Repository layout

```text
hubs/forgejo/actions/init-pwsh/
  action.yml
  dist/main.js
  dist/post.js
```

For internal Forgejo publishing, mirror this directory into a dedicated repository:

```text
git.redsoft.internal/arachne/init-pwsh
```

Then workflows can use:

```yaml
- uses: arachne/init-pwsh@v1
```

## Expected workflow contract

Arachne dispatches service inputs:

```text
build_id
arachne_callback
arachne_token
```

The action discovers those values from the workflow dispatch event payload when explicit `with:` inputs are omitted.

## MVP behavior

`init-pwsh` prepares PowerShell interception for following steps:

1. create a temporary work directory;
2. create wrapper commands for `powershell` and `pwsh`;
3. prepend the wrapper directory to `PATH` for following steps;
4. mirror subsequent PowerShell output to the original Forgejo log and to Arachne log files;
5. on teardown, send Arachne log blocks and settle the thread.

## Split step logs

The desired log model is not one giant `runner-log` blob. `init-pwsh` should keep two levels of logs:

```text
runner.log              # full job log, useful for archive/debug
steps/
  001-powershell.log    # one PowerShell shell invocation
  001-powershell.status
  002-powershell.log
  002-powershell.status
```

The post hook should publish each `steps/*.log` as a separate Arachne `/signal` block:

```json
{
  "step": "001-powershell",
  "status": "success",
  "output": "..."
}
```

Then Arachne UI receives separate blocks:

```text
TASK [001-powershell]
...
ok: [001-powershell]

TASK [002-powershell]
...
failed: [002-powershell]
```

This keeps the workflow UX identical to a normal Forgejo workflow while making Arachne logs readable.

## Limits

The MVP depends on the runner resolving `powershell` or `pwsh` through `PATH`. If the runner invokes PowerShell by absolute path, use a runner-level shell wrapper instead.

Non-PowerShell actions after init are not captured by `init-pwsh`.

The initial step names are technical names like `001-powershell`. Nice Forgejo step names require either runner-level metadata or a later heuristic.

## Future actions

```text
arachne/init-bash
arachne/artifact
arachne/settle
arachne/flush
```

`init-bash` can use `BASH_ENV`, which is cleaner than the PowerShell PATH shim.
