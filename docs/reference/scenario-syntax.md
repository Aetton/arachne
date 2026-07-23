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
- a driver name for each dispatched operation;
- backend-specific driver inputs.

The detailed field-by-field schema will be moved here from the scenario methodical
guide once that guide is present in the repository.
