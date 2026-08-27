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

Создаёт временную VM клонированием Proxmox template через OpenTofu. Сценарий задаёт
логическую ОС и ресурсы, а ID шаблона и параметры Proxmox берутся из окружения.

```yaml
- id: vm
  spider: tofu-proxmox
  action: provision
  with:
    name: arachne-test-001
    os: redos8
    vcpus: 4
    ram_mb: 8192
    disk_gb: 40
```

Поддерживаемые ОС: `redos7`, `redos8`, `windows`. Соответствие шаблонам задаётся
через `TOFU_TEMPLATE_REDOS7`, `TOFU_TEMPLATE_REDOS8` и
`TOFU_TEMPLATE_WINDOWS`. Для диагностики ID шаблона можно явно передать как
`with.template_vm_id`, но обычным сценариям Proxmox VM ID знать не нужно.

Параметры инфраструктуры по умолчанию:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `TOFU_NODE_NAME` | `pve` | Proxmox node |
| `TOFU_DATASTORE` | `local-lvm` | datastore для клона и дисков |
| `TOFU_BRIDGE` | `vmbr0` | сетевой bridge |
| `TOFU_DISK_INTERFACE` | `scsi0` | системный диск шаблона |
| `TOFU_STATE_ROOT` | `/tmp/arachne-tofu-state` | каталог локальных state |

Endpoint и учётные данные провайдера берутся из стандартных переменных
`bpg/proxmox`, прежде всего `PROXMOX_VE_ENDPOINT` и `PROXMOX_VE_API_TOKEN`.

Каждый стенд получает отдельный `terraform.tfstate` и отдельный `TF_DATA_DIR` в
`TOFU_STATE_ROOT/<name>`. Поэтому параллельные стенды не используют один local
state.

После `apply` паук читает outputs `vm_id` и `vm_ip`. Артефакт `vm` содержит IP,
VM ID, hostname, ОС, архитектуру, тип подключения, порт, ресурсы, template VM ID,
backend и состояние. `redos7`/`redos8` используют SSH:22, `windows` — WinRM:5985.

Шаблон должен быть подготовлен к клонированию: системный диск ожидается на
`TOFU_DISK_INTERFACE`, сеть получает адрес по DHCP, а qemu-guest-agent должен быть
установлен и запущен. Для Windows нужен эквивалентный Cloudbase-Init setup.
Без рабочего guest agent OpenTofu не сможет вернуть `vm_ip`, и шаг завершится
ошибкой.

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
того, чтобы молча изображать успешную уборку.

Если бинарник `tofu` не найден, production-поведение — ошибка. Старый синтетический
VM fallback включается только явно через `TOFU_DEV_FALLBACK=true`.

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
