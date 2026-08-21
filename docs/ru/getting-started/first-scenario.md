# Первый сценарий

Самый короткий полезный путь — создать сценарий, который запускает существующий
Forgejo workflow.

Сначала в разделе **Admin → Scenarios** создайте компонент, например:

| Поле | Значение |
|---|---|
| slug | `backend` |
| label | `Backend` |
| icon | `ti-server` |
| sort order | `10` |

Затем нажмите **New scenario**, задайте slug `build-backend` и вставьте:

```yaml
label: Собрать backend
component: backend
icon: ti-hammer
accent: purple

triggers:
  - type: manual

params:
  - name: version
    label: Версия
    type: string
    required: true
    default: 1.0.0

  - name: branch
    label: Ветка
    type: select
    required: true
    source:
      type: git_branches
      step: build

steps:
  - id: build
    spider: forgejo
    action: build
    with:
      repo: backend
      workflow: build.yml
      branch: "${params.branch}"
      version: "${params.version}"
```

Выберите, какие роли и команды могут видеть и запускать сценарий, затем сохраните.
Сохранение создаёт новую версию и сразу публикует её.

После этого сценарий появится на главной странице у пользователей, прошедших две
проверки:

- у роли есть возможности `scenarios.view` и `scenarios.run`;
- ACL сценария разрешает соответствующее действие.

При запуске паук проверит наличие `.forgejo/workflows/build.yml` в выбранной ветке,
вызовет `workflow_dispatch`, дождётся результата, покажет логи и соберёт Actions-
и Nexus-артефакты.

Workflow должен объявлять все пользовательские inputs, переданные в `with`. Служебные
`build_id`, `arachne_callback` и `arachne_token` текущему пауку не нужны.

Следующий шаг — [полный синтаксис сценариев](/ru/reference/scenario-syntax) и
[контракт Forgejo](/ru/integrations/forgejo).
