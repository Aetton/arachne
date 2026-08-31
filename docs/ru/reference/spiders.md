# Пауки

Паук исполняет один шаг: запускает работу, отдаёт логи, сообщает статус, возвращает
артефакты и, если умеет, отменяет работу.

## `forgejo`

```yaml
- id: build
  spider: forgejo
  action: build
  with:
    owner: platform
    repo: backend
    workflow: build.yml
    branch: main
    version: 1.2.3
    upload: true
```

Управляющие ключи:

| Ключ | Обязательный | Назначение |
|---|---:|---|
| `repo` | да | репозиторий |
| `workflow` | да | имя или путь workflow |
| `owner` | нет | владелец, иначе `FORGEJO_OWNER` |
| `ref` | нет | ref для dispatch |
| `branch` | нет | ref, если нет `ref` |
| `component` | нет | подпись в системном логе |

Остальные ключи становятся строковыми `workflow_dispatch.inputs`; boolean идёт как
`true`/`false`. Приоритет ref: `ref`, `branch`, `main`.

Паук заранее проверяет наличие workflow на ref, запускает его с
`return_run_info: true`, а при отсутствии ID ищет свежий dispatch run. Статус и логи
он читает через Forgejo API. Поддерживаются plain text и ZIP-логи v16; файлы ZIP
оборачиваются в группы `Forgejo job: ...`.

Артефакты берутся из Actions API и из строк лога с Nexus URL или фразой
`uploaded to <repo>/<path>`. Просроченные Actions artifacts пропускаются.

Отмена вызывает Forgejo endpoint `/cancel`. Значения inputs с `token`, `secret`
или `password` в имени маскируются в диагностике HTTP-ошибок.

## `ansible-local`

Запускает `ansible-playbook` внутри контейнера.

```yaml
- id: deploy
  spider: ansible-local
  action: deploy
  with:
    playbook: update-stage.yml
    target: "${vm.ip}"
    package: "${build.artifact}"
```

Без `playbook` выбирается `build-<component>.yml`. Скаляры становятся
`-e key=value`. Объект артефакта разворачивается в `key_name`, `key_type`,
`key_location`, `key_url` и скалярные `key_<metadata>`.

Строка `uploaded to <repo>/<path>` создаёт Nexus-артефакт. Отмена посылает процессу
`SIGTERM`.

Если бинарник или playbook не найден, запускается demo script. Такой fallback нужен
для разработки; в production проверяйте наличие настоящего playbook.

## `tofu-proxmox`

Создаёт временный стенд полным клонированием заранее подготовленного golden image.
Пользователь сценария работает с логическими параметрами стенда, а Proxmox и
OpenTofu остаются внутренней реализацией backend-а.

Минимальный сценарий:

```yaml
- id: vm
  spider: tofu-proxmox
  action: provision
  with:
    name: arachne-test-001
    os: redos8
```

В таком виде CPU, RAM, диск и сеть наследуются от golden image без изменений, а
машина живёт до явного `destroy`.

### Сколько машине жить

Для временного теста можно сразу задать срок жизни:

```yaml
- id: vm
  spider: tofu-proxmox
  action: provision
  with:
    name: quick-install-test
    os: redos8
    lifetime: 30m
```

Поддерживаются компактные значения:

| Значение | Смысл |
|---|---|
| `30m` | 30 минут |
| `2h` | 2 часа |
| `1d` | 1 день |

`lifetime` необязателен. Если его нет, автоматическое удаление не назначается.
При создании машины Арахна вычисляет абсолютный `expires_at` и сохраняет его в
PostgreSQL. Фоновый lifecycle reaper раз в минуту проверяет просроченные машины и
запускает тот же штатный `destroy`, что используется обычным сценарием.

Срок жизни переживает рестарт Арахны: после запуска reaper продолжает работать с
`expires_at` из базы. Прерванный cleanup имеет lease и может быть подобран заново,
если процесс умер во время удаления.

### Дополнительные ресурсы

Для разового теста можно запросить дополнительные ресурсы одновременно с TTL:

```yaml
- id: vm
  spider: tofu-proxmox
  action: provision
  with:
    name: arachne-heavy-test
    os: redos8
    lifetime: 2h
    resources:
      cpu: 8
      memory_gb: 16
      disk_gb: 80
```

Все поля `resources` необязательны и независимы:

| Поле | Назначение |
|---|---|
| `cpu` | желаемое количество vCPU |
| `memory_gb` | RAM в GiB |
| `disk_gb` | размер системного диска в GiB |

Если поле не указано, соответствующий ресурс наследуется от golden image.
Системный диск разрешено только увеличивать. Для текущих golden image базовый
размер — 40 GiB.

Поддерживаемые ОС: `redos7`, `redos8`, `windows`. Соответствие golden image,
source node и дисковой конфигурации хранится в backend environment. Обычному
сценарию не нужны VM ID, node, datastore или disk interface.

Endpoint и учётные данные provider также остаются backend-конфигурацией:

- `PROXMOX_VE_ENDPOINT`;
- `PROXMOX_VE_API_TOKEN`;
- `PROXMOX_VE_INSECURE` при необходимости.

Каждый стенд получает отдельный `terraform.tfstate`, `.terraform` и рабочий каталог
в `TOFU_STATE_ROOT/<name>`. В контейнерной установке state вынесен в persistent
volume.

После `apply` паук читает `vm_id` и `vm_ip`. Артефакт `vm` содержит IP, VM ID,
ОС, архитектуру, тип подключения, порт, backend, состояние,
`requested_resources` и `lifetime`. Структура артефакта сохраняется в run целиком,
а не восстанавливается потом из текстовой строки лога.

`redos7`/`redos8` используют SSH:22, `windows` — WinRM:5985.

Golden image должен получать сеть по DHCP и иметь работающий `qemu-guest-agent`.
Guest hostname сейчас отдельно не меняется: downstream шаги используют IP из
артефакта.

Удаление стенда выполняется отдельным шагом с тем же `name` и `os`; `resources` и
`lifetime` повторять не требуется:

```yaml
- id: cleanup
  spider: tofu-proxmox
  action: destroy
  with:
    name: arachne-test-001
    os: redos8
```

Успешный explicit destroy помечает соответствующую запись `managed_machines` как
`destroyed`. Если state отсутствует, шаг падает вместо попытки угадывать VM по
имени.

Если бинарник `tofu` не найден, production-поведение — ошибка. Синтетический VM
fallback включается только явно через `TOFU_DEV_FALLBACK=true`.

Полная настройка backend-а, API token, ACL, TLS, golden image и disk override
описана в [`operations/proxmox-opentofu.md`](../operations/proxmox-opentofu.md).

## `ansible-ovirt`

Заглушка. Возвращает выдуманную VM с IP `10.81.19.210`, реальный playbook отмечен
TODO. В production использовать нельзя.

## `scenario`

Запускает другой опубликованный сценарий как дочерний run. Требует непустой
`with.scenario`, словарь `with.params` и владельца родительского запуска. Логи,
статус и артефакты передаются родителю.

## Ошибки

| Тип | Причина |
|---|---|
| `DispatchError` | паук не смог начать работу |
| `UnknownSpider` | responder не знает паука |
| `BackendError` | backend завершился с ошибкой |
| `Cancelled` | задача отменена |
| `TransportError` | timeout или нет responder на шине |

Общий timeout нити — два часа. У Forgejo дополнительно действует
`FORGEJO_DEADLINE`.
