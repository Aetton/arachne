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

1. create a temporary log file;
2. create wrapper commands for `powershell` and `pwsh`;
3. prepend the wrapper directory to `PATH` for following steps;
4. mirror subsequent PowerShell output to the original Forgejo log and to the Arachne log file;
5. on teardown, send one Arachne log block and settle the thread.

## Limits

The MVP depends on the runner resolving `powershell` or `pwsh` through `PATH`. If the runner invokes PowerShell by absolute path, use a runner-level shell wrapper instead.

Non-PowerShell actions after init are not captured by `init-pwsh`.

## Future actions

```text
arachne/init-bash
arachne/artifact
arachne/settle
arachne/flush
```

`init-bash` can use `BASH_ENV`, which is cleaner than the PowerShell PATH shim.
