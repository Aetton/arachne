# Пауки

Паук исполняет один шаг: запускает работу, отдаёт логи, сообщает статус, возвращает артефакты и, если умеет, отменяет работу.

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

Остальные ключи становятся строковыми `workflow_dispatch.inputs`; boolean идёт как `true`/`false`. Приоритет ref: `ref`, `branch`, `main`.

Паук заранее проверяет наличие workflow на ref, запускает его с `return_run_info: true`, а при отсутствии ID ищет свежий dispatch run. Статус и логи он читает через Forgejo API. Поддерживаются plain text и ZIP-логи v16; файлы ZIP оборачиваются в группы `Forgejo job: ...`.

Артефакты берутся из Actions API и из строк лога с Nexus URL или фразой `uploaded to <repo>/<path>`. Просроченные Actions artifacts пропускаются.

Отмена вызывает Forgejo endpoint `/cancel`. Значения inputs с `token`, `secret` или `password` в имени маскируются в диагностике HTTP-ошибок.

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

Без `playbook` выбирается `build-<component>.yml`. Скаляры становятся `-e key=value`. Объект артефакта разворачивается в `key_name`, `key_type`, `key_location`, `key_url` и скалярные `key_<metadata>`.

Строка `uploaded to <repo>/<path>` создаёт Nexus-артефакт. Отмена посылает процессу `SIGTERM`.

Если бинарник или playbook не найден, запускается demo script. Такой fallback нужен для разработки; в production проверяйте наличие настоящего playbook.

## `tofu-proxmox`

Создаёт временную QEMU VM в Proxmox через OpenTofu. Пользовательский контракт намеренно не содержит Proxmox/OpenTofu internals.

### Минимальный provision

```yaml
- id: vm
  spider: tofu-proxmox
  action: provision
  with:
    name: arachne-test-001
    os: redos8
```

Если `image` не указан, `os` используется как ключ Golden Image profile.

То есть `os: redos8` означает: найти enabled profile `redos8`, получить из него VM ID Proxmox template, затем live-прочитать конфигурацию template из Proxmox API.

### Выбор конкретного Golden Image

Если одного образа на семейство ОС недостаточно:

```yaml
- id: vm
  spider: tofu-proxmox
  action: provision
  with:
    name: clean-test
    os: redos8
    image: redos8-clean
```

`os` описывает семейство гостя и connection contract. `image` выбирает конкретный Golden Image profile.

Golden Image profiles управляются в **Control -> Golden Images**. В PostgreSQL хранится mapping `profile -> template VM ID`; node, CPU, RAM, disks и storage читаются напрямую из Proxmox.

### Lifetime

```yaml
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

`lifetime` необязателен. Если его нет, auto-delete не назначается.

После provision Arachne вычисляет абсолютный `expires_at` и сохраняет его в `managed_machines`. Lifecycle reaper раз в минуту ищет просроченные VM и вызывает обычный `tofu-proxmox destroy`.

TTL переживает restart приложения, потому что время истечения хранится в PostgreSQL, а не в памяти scheduler job.

### Resource overrides

```yaml
with:
  name: arachne-heavy-test
  os: redos8
  lifetime: 2h
  resources:
    cpu: 8
    memory_gb: 16
    disk_gb: 80
```

Все поля независимы:

| Поле | Назначение |
|---|---|
| `resources.cpu` | желаемое число vCPU |
| `resources.memory_gb` | RAM в GiB |
| `resources.disk_gb` | желаемый размер системного диска в GiB |

Если поле не указано, соответствующий ресурс наследуется от Golden Image.

Disk можно только увеличивать относительно **фактического** system disk template. Spider не использует `TOFU_DEFAULT_GOLDEN_DISK_GB` или подобную env-константу как baseline.

### Discovery перед OpenTofu

Provision выполняет такой путь:

```text
image/os profile key
  -> PostgreSQL Golden Image profile
  -> template VM ID
  -> Proxmox cluster resources
  -> source node
  -> QEMU config
  -> CPU/RAM/system disk/storage
  -> OpenTofu variables
```

Это означает, что scenario не содержит:

```text
template_vm_id
node_name
template_node_name
clone_datastore_id
disk interface
disk datastore
provider configuration
```

Если такие данные нужны spider-у, он обязан получить их из Golden Image mapping и Proxmox API.

### Broken profile

Новый provision блокируется, если профиль:

- отсутствует;
- disabled;
- указывает на исчезнувший VM ID;
- указывает на объект, который больше не template;
- недоступен сервисному token;
- не может быть прочитан через Proxmox API.

UI Golden Images при этом сохраняет профиль и показывает broken state, чтобы администратор видел сломанное соответствие.

### OpenTofu state

Каждый stand получает отдельный каталог:

```text
TOFU_STATE_ROOT/<name>/
```

Там находятся рабочая копия module, `.terraform` и `terraform.tfstate`. В Compose root вынесен в persistent volume.

Имя stand сейчас участвует в state key, поэтому конкурирующие операции с одинаковым `name` являются плохой идеей.

### VM artifact

После apply spider читает `vm_id` и `vm_ip` и возвращает structured artifact типа `vm`.

Пользовательская часть metadata включает, в зависимости от результата:

```text
os
arch
ip
connection type
port
vm_id
requested_resources
lifetime
state
```

Backend metadata сохраняются для lifecycle, но не являются пользовательским API сценария.

Если VM уже создана и известен `vm_id`, но Guest Agent ещё не вернул IP, artifact всё равно формируется. Run может завершиться ошибкой получения адреса, но managed machine не теряется и остаётся доступной для cleanup.

`redos7`/`redos8` используют SSH:22, `windows` — WinRM:5985.

### Требования к Golden Image

Для нормального clone нужны:

- QEMU template;
- DHCP или другой механизм получения адреса, совместимый с текущим сценарием;
- `qemu-guest-agent`;
- clone-safe machine identity;
- для Linux корректная подготовка machine-id/SSH identity;
- для Windows clone-ready/generalized image.

Текущий организационный baseline основного system disk — 40 GiB. Это правило подготовки образов, а не зашитая настройка spider-а.

### Destroy

Ручной cleanup:

```yaml
- id: cleanup
  spider: tofu-proxmox
  action: destroy
  with:
    name: arachne-test-001
    os: redos8
```

`resources`, `lifetime`, VM ID, node и storage повторять не нужно.

При provision backend metadata конкретного созданного stand сохраняются в `managed_machines`. Поэтому смена Golden Image mapping позже не должна ломать destroy старой VM.

Успешный destroy возвращает lifecycle VM artifact со `state: destroyed`, а managed machine получает `destroyed_at`.

### TTL cleanup states

```text
running -> destroying -> destroyed
              |
              v
          reap_failed
              |
              +---- retry
```

Destroy claim имеет lease. Если Arachne умерла посреди cleanup, запись может быть подобрана повторно после истечения lease.

### Backend environment

Для Proxmox нужны только connection/auth параметры:

```text
PROXMOX_VE_ENDPOINT
PROXMOX_VE_API_TOKEN
PROXMOX_VE_INSECURE
```

Плюс runtime paths OpenTofu:

```text
TOFU_ROOT
TOFU_STATE_ROOT
TOFU_DEV_FALLBACK
```

Template/node/storage mappings в environment больше не являются частью архитектуры.

Полная эксплуатационная документация:

- [Golden Images](/ru/operations/golden-images)
- [Proxmox и OpenTofu](/ru/operations/proxmox-opentofu)
- [Диагностика](/ru/operations/troubleshooting)

## `ansible-ovirt`

Заглушка. Возвращает выдуманную VM с IP `10.81.19.210`, реальный playbook отмечен TODO. В production использовать нельзя.

## `scenario`

Запускает другой опубликованный сценарий как дочерний run. Требует непустой `with.scenario`, словарь `with.params` и владельца родительского запуска. Логи, статус и артефакты передаются родителю.

## Ошибки

| Тип | Причина |
|---|---|
| `DispatchError` | паук не смог начать работу |
| `UnknownSpider` | responder не знает паука |
| `BackendError` | backend завершился с ошибкой |
| `Cancelled` | задача отменена |
| `TransportError` | timeout или нет responder на шине |

Общий timeout нити — два часа. У Forgejo дополнительно действует `FORGEJO_DEADLINE`.
