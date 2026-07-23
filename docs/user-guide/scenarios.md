# Scenarios

Published scenarios live in PostgreSQL. The file `config/scenarios.yaml` is only a
bootstrap seed: a slug is imported when it does not already exist in the database.

Editing a scenario creates a new version. Existing runs retain both the version ID
and an immutable definition snapshot, so later changes cannot rewrite execution history.

Scenario access combines capabilities, roles, teams, and per-scenario ACLs.
