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

Use the `scenario` spider when one scenario must run other scenarios explicitly as
ordered steps. Unlike a `chain` trigger, this keeps orchestration inside the parent
run, passes parameters deliberately, streams child logs, waits for completion, and
propagates child failure to the parent.

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

  - id: build-gateway
    spider: scenario
    action: run
    with:
      scenario: build-broker-gateway
      params:
        version: "${params.version}"
        release: "${params.release}"
        branch: "${params.branch}"
```

`with.scenario` is the exact child scenario slug. `with.params` is an optional
mapping passed to the child run after normal `${...}` resolution. Child scenarios
are regular persisted runs with their own run IDs and history records.

Steps remain sequential: the next child scenario starts only after the previous one
returns `success`. A failed or cancelled child stops the parent scenario.

The detailed field-by-field schema will be moved here from the scenario methodical
guide once that guide is present in the repository.
