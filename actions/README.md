# Arachne Actions Export

Staging folder for exporting Arachne utility-belt actions into the standalone `arachne/actions` repository.

This folder is intentionally copy-friendly:

```text
actions/
  forgejo/
    init-bash/
      action.yml
      dist/
        main.js
        post.js
```

## Export flow

Clone/pull `arachne`, then copy this folder into the standalone empty actions repository:

```bash
cp -a /path/to/arachne/actions/. /path/to/actions/
```

## PowerShell action

`init-pwsh` is not stored in this repository yet. Copy it from the old `init-pwsh` repository into:

```text
forgejo/init-pwsh/
```

Expected final standalone repository layout:

```text
forgejo/
  init-pwsh/
    action.yml
    dist/
      main.js
      post.js

  init-bash/
    action.yml
    dist/
      main.js
      post.js
```

## Forgejo usage

Bash:

```yaml
- name: Init Arachne telemetry
  uses: https://git.redsoft.internal/arachne/actions/forgejo/init-bash@v1
```

PowerShell:

```yaml
- name: Init Arachne telemetry
  uses: https://git.redsoft.internal/arachne/actions/forgejo/init-pwsh@v1
```
