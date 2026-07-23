# Сценарии Арахны

Сценарий Арахны — это YAML-описание формы запуска, правил доступа, триггеров и
последовательности шагов. Каждый шаг передаётся одному из пауков (`spider`), а
его основной артефакт можно использовать в следующих шагах.

Этот файл описывает синтаксис текущей реализации. Эталон полного seed-файла:
[`scenarios.yaml.example`](scenarios.yaml.example).

## Минимальный сценарий

```yaml
scenarios:
  build-backend:
    label: "Собрать backend"
    component: backend
    icon: "ti-server"
    accent: purple

    access:
      view:
        match: all
        roles: [developer]
        teams: [backend]
      run:
        match: all
        roles: [developer]
        teams: [backend]

    triggers:
      - type: manual

    params:
      - name: version
        label: "Версия"
        type: string
        required: true
        default: "1.0.0"

      - name: upload
        label: "Загрузить в Nexus"
        type: boolean
        default: true

      - name: branch
        label: "Ветка"
        type: string
        required: true
        default: main

    steps:
      - id: build
        spider: forgejo
        action: build
        with:
          component: backend
          repo: backend
          workflow: backend-build.yml
          version: "${params.version}"
          upload: "${params.upload}"
          branch: "${params.branch}"
```

Обязательные поля определения сценария: `label`, `component`, `steps`.
Список `steps` не может быть пустым. У каждого шага обязательны уникальный
`id`, `spider` и `action`.

## Где хранятся сценарии

`config/scenarios.yaml` используется для первоначального наполнения базы.
При старте Арахна импортирует только те сценарии, slug которых ещё отсутствует
в БД. Уже существующий сценарий файл не перезаписывает.

После импорта источником истины становится PostgreSQL:

- редактирование сценария создаёт новую версию;
- опубликованная версия используется для новых запусков;
- запуск сохраняет ID версии и снимок определения;
- YAML можно экспортировать из административного интерфейса.

Поэтому изменение уже импортированного сценария в `scenarios.yaml` само по себе
ничего не изменит. Редактируйте его в административном интерфейсе либо
импортируйте как новый slug.

## Структура seed-файла

```yaml
components:
  backend:
    label: "Backend"
    icon: "ti-server"

scenarios:
  build-backend:
    # определение сценария
```

### `components`

Компоненты импортируются из YAML только при первичной инициализации. После
импорта справочник компонентов, его подписи, иконки и порядок хранятся в БД и
редактируются на странице управления сценариями. Runtime не читает компоненты
из файла.

Словарь компонентов для группировки и оформления сценариев.

| Поле | Обязательное | Назначение |
|---|---:|---|
| ключ словаря | да | Стабильный slug компонента |
| `label` | да | Отображаемое имя |
| `icon` | нет | CSS-класс иконки Tabler, например `ti-server` |
| `sort_order` | нет | Порядок группы на dashboard |

Значение `scenario.component` должно ссылаться на slug компонента. Компоненты
также используются командами RBAC как область ответственности.

### `scenarios`

Словарь сценариев. Ключ каждого элемента — стабильный slug сценария:

```yaml
scenarios:
  build-redos8-agent:
    label: "Собрать агент для РЕД ОС 8"
    component: rpm-modern
    steps: []
```

Slug используется в URL, истории запусков, ACL, цепочках и API. Не меняйте его
как обычный заголовок: новый slug означает новый сценарий.

## Поля сценария

| Поле | Тип | Обязательное | Назначение |
|---|---|---:|---|
| `label` | string | да | Название в интерфейсе |
| `component` | string | да | Slug компонента |
| `icon` | string | нет | CSS-класс Tabler Icons |
| `accent` | string | нет | Цветовой акцент карточки |
| `access` | mapping | нет | ACL для просмотра и запуска |
| `triggers` | list | нет | Способы запуска |
| `params` | list | нет | Поля формы и входные параметры |
| `steps` | list | да | Непустая последовательность шагов |

Неизвестные декоративные поля могут сохраниться в определении, но не обязаны
использоваться текущим интерфейсом. Не рассчитывайте на них как на контракт.

## Параметры

Параметры объявляются в `params` и становятся доступны как
`${params.<name>}`.

```yaml
params:
  - name: release
    label: "Канал"
    type: choice
    required: true
    options: [stable, staging, dev]

  - name: debug
    label: "Отладочная сборка"
    type: boolean
    default: false
```

| Поле | Обязательное | Назначение |
|---|---:|---|
| `name` | да | Имя параметра и ключ в `${params.name}` |
| `label` | да | Подпись в форме |
| `type` | да | `string`, `choice` или `boolean` |
| `required` | нет | Делает текстовое поле обязательным в браузере |
| `default` | нет | Начальное значение в форме |
| `options` | для `choice` | Допустимые варианты выпадающего списка |

Особенности текущего интерфейса:

- `string` и неизвестные типы отображаются как текстовое поле;
- `choice` отображается как список `options`;
- `boolean` отображается как checkbox и передаётся настоящим boolean;
- остальные значения формы передаются строками;
- `default` — прежде всего значение формы, а не универсальная серверная
  подстановка.

Последний пункт важен для автоматических триггеров: `schedule` должен передать
нужные `params` явно. `chain` сейчас запускает следующий сценарий с пустым
словарём параметров.

## Подстановки

В `with` поддерживаются две формы ссылок:

```yaml
with:
  version: "${params.version}"
  target_ip: "${create-vm.ip}"
```

### Параметры сценария

```text
${params.<name>}
```

Пример:

```yaml
branch: "${params.branch}"
```

### Артефакты предыдущих шагов

```text
${<step-id>.<field>}
```

Используется только первый, основной артефакт шага.

Общие поля артефакта:

| Ссылка | Значение |
|---|---|
| `${build.name}` | Имя артефакта |
| `${build.type}` | Тип: `nexus`, `vm` и т. п. |
| `${build.location}` | Внутренний путь или идентификатор |
| `${build.download_url}` | URL загрузки, если он есть |
| `${build.artifact}` | Целый объект артефакта |

Дополнительно доступны поля из `artifact.metadata`, например `${vm.ip}`,
`${vm.os}`, `${vm.conn}` или `${build.repo}`.

Если вся строка состоит из одной ссылки, сохраняется исходный тип значения:
boolean остаётся boolean, а `${build.artifact}` — объектом. Внутри более длинной
строки значение превращается в текст:

```yaml
enabled: "${params.debug}"                # boolean
name: "stage-${params.version}"           # string
package: "${build.artifact}"              # Artifact
```

Ссылаться можно только на уже завершившийся шаг. Ссылка на неизвестный шаг
завершит сценарий ошибкой. Ссылка на поле отсутствующего артефакта вернёт
`null` либо пустую строку при текстовой подстановке.

Подстановки рекурсивно обрабатываются во вложенных словарях. В списках
обрабатываются скалярные элементы; вложенные словари внутри списка текущий
резолвер рекурсивно не разворачивает.

## Шаги

```yaml
steps:
  - id: build
    spider: forgejo
    action: build
    kind: build
    needs: []
    with:
      repo: backend
      workflow: build.yml
```

| Поле | Тип | Обязательное | Назначение |
|---|---|---:|---|
| `id` | string | да | Уникальное имя шага и namespace его результата |
| `spider` | string | да | Зарегистрированный паук |
| `action` | string | да | Операция паука |
| `kind` | string | нет | Канал маршрутизации; обычно определяется пауком |
| `needs` | list | нет | Зарезервированные зависимости шага |
| `with` | mapping | нет | Аргументы паука |

Шаги выполняются последовательно сверху вниз. При первом `failed` или
`cancelled` оставшиеся шаги не запускаются.

`needs` уже входит в модель шага и передаётся по шине, но текущий оркестратор не
использует его для сортировки, параллельного запуска или пропуска шагов. Пока
порядок определяется исключительно расположением в YAML.

## Пауки

### `forgejo`

Запускает Forgejo Actions workflow и ждёт телеметрию от Arachne Hub.

```yaml
- id: build
  spider: forgejo
  action: build
  with:
    owner: redsoft
    repo: backend
    workflow: backend-build.yml
    branch: main
    version: "${params.version}"
    upload: "${params.upload}"
```

| Ключ `with` | Обязательное | Назначение |
|---|---:|---|
| `repo` | да | Репозиторий Forgejo |
| `workflow` | да | Имя файла либо путь `.forgejo/workflows/...` |
| `owner` | нет | Владелец; иначе `FORGEJO_OWNER` |
| `ref` | нет | Git ref для dispatch |
| `branch` | нет | Используется как ref, если `ref` не задан |
| `component` | нет | Имя компонента в логах |
| остальные ключи | нет | Передаются как строковые workflow inputs |

Приоритет ref: `ref` → `branch` → `main`. Boolean-входы превращаются в строки
`true`/`false`.

Арахна сама добавляет служебные inputs:

- `build_id`;
- `arachne_callback`;
- `arachne_token`.

Workflow должен принимать их и отправлять телеметрию в callback. Секреты не
следует прописывать в сценарии: используйте secrets Forgejo и переменные
окружения Арахны.

Основной артефакт обычно имеет тип `nexus`. Паук распознаёт URL вида
`.../repository/<repo>/<path>` и строки `uploaded to <repo>/<path>`.

### `ansible-local`

Запускает локальный `ansible-playbook`.

```yaml
- id: deploy
  spider: ansible-local
  action: deploy
  with:
    playbook: deploy-stage.yml
    target: "${vm.ip}"
    package: "${build.artifact}"
```

| Ключ `with` | Назначение |
|---|---|
| `playbook` | Файл относительно `ANSIBLE_PLAYBOOKS_DIR` |
| `component` | Используется для имени playbook по умолчанию и dev fallback |
| остальные скаляры | Передаются как `ansible-playbook -e key=value` |
| целый Artifact | Разворачивается в набор `key_name`, `key_type`, `key_location`, `key_url` и metadata |

Если `playbook` не задан, используется `build-<component>.yml`.

### `tofu-proxmox`

Создаёт VM через OpenTofu и возвращает артефакт типа `vm`.

```yaml
- id: vm
  spider: tofu-proxmox
  action: provision
  with:
    name: "stage-${params.version}"
    os: redos8
    vcpus: 4
    ram_mb: 8192
    disk_gb: 40
```

Поддерживаемые входы текущей реализации: `name`, `os`, `vcpus`, `ram_mb`,
`disk_gb`. Артефакт содержит `name`, `location` и metadata: `os`, `arch`,
`hostname`, `ip`, `conn`, `ssh_port`, `vcpus`, `ram_mb`, `disk_gb`, `backend`,
`state`.

### `ansible-ovirt`

Имеет тот же тип результата `vm`, что и `tofu-proxmox`, поэтому последующие
шаги могут использовать одинаковые `${vm.ip}`, `${vm.os}` и `${vm.conn}`.

Сейчас это каркас: реальный playbook oVirt ещё не подключён. Не используйте его
в production-сценариях, пока реализация паука не завершена.

## Триггеры

### Ручной запуск

```yaml
triggers:
  - type: manual
```

Показывает обычную форму запуска. Сам триггер фоновой логики не создаёт.

### Расписание

```yaml
triggers:
  - type: schedule
    cron: "0 2 * * *"
    params:
      branch: main
      version: nightly
      upload: true
```

`cron` — стандартное пятичастное cron-выражение APScheduler. `params`
передаются сценарию при каждом запуске. Если `cron` отсутствует, триггер
игнорируется.

### Цепочка

```yaml
triggers:
  - type: chain
    after: build-backend
    on: success
```

| Поле | Обязательное | Значение |
|---|---:|---|
| `after` | да | Slug предыдущего сценария |
| `on` | нет | `success`, `failed` или `cancelled`; по умолчанию `success` |

Текущая реализация не передаёт параметры или артефакты предыдущего запуска:
следующий сценарий получает пустые `params`.

## ACL: роли и команды

Администратор всегда имеет доступ ко всем сценариям и обходит ACL.
Для остальных пользователей проверяются два слоя:

1. роль должна содержать глобальное разрешение `scenarios.view` или
   `scenarios.run`;
2. ACL конкретного сценария должен разрешать соответствующее действие роли
   и/или команде пользователя.

```yaml
access:
  view:
    match: all
    roles: [developer]
    teams: [backend, protocol]

  run:
    match: all
    roles: [developer]
    teams: [backend]
```

Поддерживаемые действия ACL: `view`, `run`, `edit`, `manage`.

| `match` | Поведение |
|---|---|
| `all` | Должны совпасть роль и команда, если обе группы указаны |
| `any` | Достаточно совпадения роли или команды |

Для правила только по роли или только по команде используйте `match: all`.
В текущей реализации отсутствующая группа считается совпавшей; поэтому
`match: any` с пустым `roles` либо `teams` фактически разрешит доступ любому
пользователю с соответствующим глобальным permission. `any` безопасно
использовать только тогда, когда заполнены обе группы.

Если ACL для действия отсутствует, пользователь без роли `admin` доступа не
получает. Роли могут наследовать другие роли; при проверке учитывается весь
наследуемый набор.

В seed-YAML команды записываются slug’ами:

```yaml
teams: [backend]
```

После сохранения через текущую административную форму ACL может экспортировать
в поле `teams` числовые ID команд. Проверка доступа понимает и ID, и slug.

## Многошаговый пример

```yaml
scenarios:
  create-stage:
    label: "Создать тестовый стенд"
    component: stage
    icon: "ti-plus"
    accent: green

    access:
      view: {match: all, roles: [developer], teams: [backend]}
      run:  {match: all, roles: [developer], teams: [backend]}

    triggers:
      - type: manual

    params:
      - name: version
        label: "Версия"
        type: string
        required: true
        default: "1.0.0"
      - name: os
        label: "ОС"
        type: choice
        required: true
        options: [redos7, redos8, windows]
      - name: stage_name
        label: "Имя стенда"
        type: string
        required: true
        default: test-stage

    steps:
      - id: build
        spider: forgejo
        action: build
        with:
          repo: backend
          workflow: backend-build.yml
          version: "${params.version}"

      - id: vm
        spider: tofu-proxmox
        action: provision
        with:
          name: "${params.stage_name}-${params.os}"
          os: "${params.os}"

      - id: deploy
        spider: ansible-local
        action: deploy
        with:
          playbook: deploy-stage.yml
          target: "${vm.ip}"
          conn: "${vm.conn}"
          package: "${build.artifact}"
```

## Проверка перед публикацией

- Slug сценария стабилен и не содержит пробелов.
- `label`, `component` и непустой `steps` заданы.
- У каждого шага есть уникальные `id`, `spider`, `action`.
- Все `${params.X}` ссылаются на объявленные параметры.
- Все `${step.field}` ссылаются только на предыдущие шаги.
- Для `forgejo` заданы существующие `repo`, `workflow` и ref.
- Workflow принимает служебные inputs Арахны и отправляет hub-телеметрию.
- Для автоматических триггеров параметры указаны явно.
- Для non-admin заданы и глобальные permissions роли, и ACL сценария.
- Секретов, токенов и паролей в YAML нет.

## Текущие ограничения

- Шаги исполняются последовательно; параллельного DAG пока нет.
- `needs` пока не влияет на порядок выполнения.
- Валидация проверяет структуру, но не существование пауков, workflow,
  playbook, параметров и ссылок.
- `chain` не передаёт параметры и артефакты между сценариями.
- Автоматические триггеры не подставляют значения `default` из формы.
- Сценарий без ACL закрыт для всех пользователей, кроме `admin`.
- Изменение seed-YAML не обновляет уже импортированный сценарий.

Если редактор в будущем будет использовать этот файл как встроенную справку,
эти ограничения стоит показывать рядом с соответствующими полями, а не прятать
в одном общем предупреждении.
