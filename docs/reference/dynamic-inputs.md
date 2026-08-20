# Dynamic scenario inputs

Arachne can populate select inputs dynamically when the available values come from an external source.

## Git branch selector

Use `type: select` with `source.type: git_branches`:

```yaml
params:
  - name: branch
    label: Branch
    type: select
    required: true
    default: develop
    source:
      type: git_branches
```

When neither `source.repo` nor `source.step` is specified, Arachne uses the Forgejo step with `id: build` as the repository source:

```yaml
steps:
  - id: build
    spider: forgejo
    action: build
    with:
      repo: broker
      workflow: build.yml
      branch: "${params.branch}"
```

Repository resolution follows this priority:

1. `source.repo` when explicitly specified;
2. the Forgejo step named by `source.step`;
3. the Forgejo step with `id: build`.

This allows composite scenarios to select a branch from a repository other than the repository that owns the build workflow. For example, a desktop build can select a frontend branch explicitly:

```yaml
params:
  - name: frontend_branch
    label: Frontend branch
    type: select
    required: true
    default: develop
    source:
      type: git_branches
      repo: frontend

steps:
  - id: build
    spider: forgejo
    action: build
    with:
      repo: desktop
      workflow: build.yml
      frontend_branch: "${params.frontend_branch}"
```

`source.owner` is optional and defaults to `FORGEJO_OWNER`.

Branch lists are loaded from the Forgejo API and cached briefly. The cache TTL defaults to 30 seconds and can be changed with `INPUT_SOURCE_CACHE_TTL`.

If branch loading fails, the selector is disabled and the lookup error is shown in the form instead of falling back to free-form text.

Static `type: choice` inputs remain unchanged and continue to use their configured `options` list.
