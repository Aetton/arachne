# Scenario syntax

This page is the canonical reference for scenario YAML and the future source for the
editor's built-in help.

## Access rules

```yaml
access:
  view:
    match: all
    roles: [developer]
    teams: [backend]
  run:
    match: all
    roles: [developer, release-engineer]
    teams: [backend]
```

`match: all` requires a matching role and team. `match: any` accepts either axis.
Administrators bypass scenario ACLs.

## Definition areas

A scenario definition contains:

- form parameters;
- manual, scheduled, or chained triggers;
- ordered steps;
- a spider name for each dispatched operation;
- backend-specific spider inputs.

## References and substitutions

A step may reference scenario parameters and the primary artifact produced by an
already completed step:

```yaml
with:
  version: "${params.version}"
  artifact: "${build.artifact}"
  package_url: "${build.download_url}"
  label: "broker-${params.version}"
```

Supported forms are `${params.<name>}` and `${<step-id>.<artifact-field>}`. Artifact
fields include the normal artifact attributes and keys stored in artifact metadata.

Resolution is recursive through mappings and lists at any depth:

```yaml
with:
  params:
    targets:
      - name: broker
        packages:
          - version: "${params.version}"
            source: "${build.download_url}"
```

A string containing only one reference preserves the referenced value's type. This
allows booleans, numbers, `null`, and complete artifact objects to pass through
without string conversion. A reference embedded into a larger string is converted
to text.

Unknown parameters, unknown step IDs, malformed references, and unsupported
reference forms fail the step instead of being silently replaced with empty values.
References currently contain exactly two path segments; arbitrary expressions and
paths such as `${params.build.version}` are not supported.

## YAML anchors and aliases

Arachne parses YAML with PyYAML `safe_load`, so ordinary anchors, aliases, and YAML
merge keys are accepted on YAML input:

```yaml
x-broker-params: &broker-params
  version: "${params.version}"
  release: "${params.release}"
  branch: "${params.branch}"

steps:
  - id: build-auth
    spider: scenario
    action: run
    with:
      scenario: build-broker-auth
      params: *broker-params

  - id: build-gateway
    spider: scenario
    action: run
    with:
      scenario: build-broker-gateway
      params:
        <<: *broker-params
        upload: true
```

Anchors are YAML document syntax, not part of the stored scenario model. During
parsing they are expanded into normal mappings and lists. Scenario definitions are
then persisted as JSON-compatible database values, so anchor names and alias
relationships are not preserved when a scenario is reopened or exported. The
expanded values remain correct, but the editor/export round trip may produce
repeated YAML instead of anchors.

Use anchors as import-time authoring sugar when that loss of formatting is
acceptable. Preserving anchors across editor saves would require storing the source
YAML or using a round-trip YAML parser and a YAML-native persistence model; it should
not be bolted onto runtime reference resolution.

## Running another scenario

Use the `scenario` spider when one scenario must run another scenario as one of its
ordered steps. Unlike a `chain` trigger, this keeps orchestration inside the parent
run, passes parameters deliberately, streams child logs, waits for completion, and
propagates the child terminal status to the parent step.

### Minimal form

```yaml
steps:
  - id: build-auth
    spider: scenario
    action: run
    with:
      scenario: build-broker-auth
```

The supported action is `run`. Other action names are not part of the scenario
spider contract and must not be used.

### Inputs

`with.scenario`
: Required. Exact slug of the published child scenario. It must be a non-empty
  string. An unknown or unavailable slug fails the parent step when Arachne tries to
  start the child run.

`with.params`
: Optional mapping passed to the child scenario. When omitted, the child receives an
  empty parameter mapping. Values are resolved through the normal `${...}` mechanism
  before dispatch, including nested mappings and lists.

Example with explicit parameter forwarding:

```yaml
steps:
  - id: build-auth
    spider: scenario
    action: run
    with:
      scenario: build-broker-auth
      params:
        version: "${params.version}"
        release: "${params.release}"
        branch: "${params.branch}"
```

`with.params` must be a mapping. Lists, strings, numbers, and other scalar values are
rejected.

Parameters are not forwarded automatically. Every value required by the child must
be declared explicitly under `with.params`:

```yaml
# Parent parameter "version" is forwarded.
params:
  version: "${params.version}"
```

### Execution and logs

The child is created as a regular persisted Arachne run with its own run ID, scenario
snapshot, history entry, logs, status, and artifacts. The parent step waits until the
child reaches a terminal state.

Child log records are copied into the parent step and prefixed with the child
scenario and child step identifiers:

```text
[build-broker-auth/checkout] cloning repository
[build-broker-auth/build] compilation complete
```

This keeps the complete orchestration visible from the parent run while preserving
the child as an independently inspectable run.

### Status propagation

The child terminal status becomes the status of the parent `scenario` step:

- `success` lets the parent continue to its next step;
- `failed` fails the parent step and stops normal sequential execution;
- `cancelled` marks the parent step cancelled and stops normal sequential execution.

Because ordinary scenario steps are sequential, a list of `scenario` steps runs one
child after another. The next child starts only after the previous child returns
`success`.

```yaml
steps:
  - id: build-auth
    spider: scenario
    action: run
    with:
      scenario: build-broker-auth

  - id: build-gateway
    spider: scenario
    action: run
    with:
      scenario: build-broker-gateway
```

### Artifacts

Artifacts produced by the child are exposed as artifacts of the parent step after
the child completes. Each copied artifact includes metadata identifying its origin:

- `scenario`: child scenario slug;
- `child_run_id`: persisted child run ID.

The artifact name, type, and download URL are preserved when available.

### `scenario` spider versus `chain` trigger

Use `scenario` when the parent owns the orchestration:

- the child is an explicit ordered step;
- parameters are passed deliberately;
- the parent waits for the child;
- logs and artifacts are visible in the parent;
- child failure affects the parent.

Use `chain` when a completed run should independently trigger another scenario:

- the downstream run is event-driven;
- it is not an ordered step of the upstream scenario;
- the upstream run does not wait for it;
- the downstream result does not alter the already completed upstream run.

### Current limitations

The current implementation has the following limits:

- cancelling the parent run does not yet propagate cancellation to an already
  running child scenario;
- recursive orchestration is not yet guarded, so a scenario can directly or
  indirectly invoke itself; authors must avoid cycles;
- child execution and live log forwarding currently depend on the child run being
  available through the same in-process run engine;
- access checks are performed when a user starts the parent scenario, but the
  internal child dispatch does not currently perform a separate child ACL check;
- caller identity is not yet propagated into the child run, so audit ownership of
  internally launched children requires further work.

These are runtime limitations, not supported DSL features. Scenario authors should
keep orchestration acyclic and avoid relying on parent cancellation until explicit
child cancellation is implemented.
