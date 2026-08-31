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

Создаёт временную VM полным клонированием заранее подготовленного Proxmox golden
template через OpenTofu.

Обычный сценарий задаёт только имя стенда и логическую ОС:

```yaml
- id: vm
  spider: tofu-proxmox
  action: provision
  with:
    name: arachne-test-001
    os: redos8
```

CPU, RAM, диски и сеть **не переопределяются**. Их источником правды остаётся
золотой шаблон. Для наших золотых образов системный диск принят равным 40 GiB.

Поддерживаемые ОС: `redos7`, `redos8`, `windows`. Соответствие шаблонам задаётся
через `TOFU_TEMPLATE_REDOS7`, `TOFU_TEMPLATE_REDOS8` и
`TOFU_TEMPLATE_WINDOWS`. Значение — Proxmox VM ID template.

Source node шаблона задаётся соответствующей переменной:

- `TOFU_TEMPLATE_REDOS7_NODE`;
- `TOFU_TEMPLATE_REDOS8_NODE`;
- `TOFU_TEMPLATE_WINDOWS_NODE`.

На single-node Proxmox этот node одновременно используется как target node. В
multi-node окружении target можно переопределить глобально через
`TOFU_NODE_NAME`. Для cross-node clone на non-shared storage можно задать
`TOFU_CLONE_DATASTORE`.

Для диагностики те же значения можно передать через `with.template_vm_id`,
`with.template_node_name`, `with.node_name` и `with.clone_datastore_id`, но в
обычных опубликованных сценариях Proxmox-внутренности держать не надо.

Endpoint и учётные данные provider берутся из стандартных переменных
`bpg/proxmox`:

- `PROXMOX_VE_ENDPOINT`;
- `PROXMOX_VE_API_TOKEN`;
- `PROXMOX_VE_INSECURE` при необходимости.

Каждый стенд получает отдельный `terraform.tfstate`, `.terraform` и рабочий каталог
в `TOFU_STATE_ROOT/<name>`. В контейнерной установке каталог state вынесен в
persistent volume, поэтому рестарт Арахны не лишает её возможности уничтожить
созданную VM.

После `apply` паук читает outputs `vm_id` и `vm_ip`. Артефакт `vm` содержит IP,
VM ID, ОС, архитектуру, тип подключения, порт, template VM ID, node, backend и
состояние. `redos7`/`redos8` используют SSH:22, `windows` — WinRM:5985.

Golden template должен получать сеть по DHCP и иметь работающий
`qemu-guest-agent`. Без guest agent provider не вернёт IPv4, и шаг завершится
ошибкой. Guest hostname сейчас отдельно не меняется: downstream шаги используют IP
из артефакта.

Удаление стенда выполняется отдельным шагом с тем же `name` и `os`:

```yaml
- id: cleanup
  spider: tofu-proxmox
  action: destroy
  with:
    name: arachne-test-001
    os: redos8
```

`destroy` использует state этого имени. Если state отсутствует, шаг падает вместо
того, чтобы угадывать VM по имени и удалять что-нибудь напрямую через API.

Если бинарник `tofu` не найден, production-поведение — ошибка. Синтетический VM
fallback включается только явно через `TOFU_DEV_FALLBACK=true`.

Полная настройка Proxmox, API token, ACL, TLS и golden templates описана в
[`operations/proxmox-opentofu.md`](../operations/proxmox-opentofu.md).

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
