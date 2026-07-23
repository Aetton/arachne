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
