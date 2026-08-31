# Proxmox и OpenTofu

`tofu-proxmox` создаёт временные VM полным клонированием заранее подготовленных
Proxmox templates. Пользователь сценария работает с человеческими Golden Image
профилями; VM ID, node, datastore, disk interface и фактические ресурсы шаблона
остаются внутренней реализацией Арахны.

## Пользовательский контракт

Минимальный сценарий:

```yaml
- id: vm
  spider: tofu-proxmox
  action: provision
  with:
    name: redvrm-test-001
    os: redos8
```

`os` одновременно используется как семейство ОС и как ключ Golden Image профиля
по умолчанию. Если для одного семейства ОС заведено несколько образов, можно явно
выбрать профиль:

```yaml
with:
  name: redvrm-clean-test
  os: redos8
  image: redos8-clean
```

Дополнительно пользователь может задать TTL и ресурсы:

```yaml
with:
  name: redvrm-heavy-test
  os: redos8
  image: redos8
  lifetime: 2h
  resources:
    cpu: 8
    memory_gb: 16
    disk_gb: 80
```

Поддерживаются:

| Поле | Что означает |
|---|---|
| `image` | Golden Image профиль; если не указан, используется `os` |
| `lifetime` | срок жизни: `30m`, `2h`, `1d` и т.п. |
| `resources.cpu` | желаемое число vCPU |
| `resources.memory_gb` | RAM в GiB |
| `resources.disk_gb` | размер системного диска в GiB |

Если resource-поле отсутствует, соответствующая характеристика наследуется от
выбранного template. Системный диск разрешено только увеличивать относительно его
реального размера в Proxmox.

## Где хранится конфигурация

В `.env` остаются только параметры подключения к Proxmox:

```dotenv
PROXMOX_VE_ENDPOINT=https://pve.example.internal:8006/
PROXMOX_VE_API_TOKEN=arachne@pve!arachne=<TOKEN_SECRET>
PROXMOX_VE_INSECURE=false
```

Golden Image mappings настраиваются через:

```text
Control -> Golden Images
```

Профиль хранит только:

```text
slug
красивое имя
семейство ОС
VM ID выбранного template
enabled/disabled
```

Арахна **не хранит копии** node, datastore, disk interface, CPU, RAM и размера
диска. Эти значения читаются напрямую из Proxmox API при открытии Golden Images
и при каждом provision.

Это позволяет перемещать template между node, менять storage или ресурсы без
правки `.env` и без синхронизации второго набора инфраструктурных данных.

## Golden Images UI

Администратор открывает `Control -> Golden Images` и создаёт профиль, например:

```text
Name:     RedOS 8
Key:      redos8
OS:       RedOS 8
Template: redos8-golden · #9002 · pve01
```

Список template строится живым запросом к Proxmox. Карточка профиля показывает
фактическое состояние выбранного template:

- имя и VM ID;
- node;
- vCPU;
- RAM;
- размер системного диска;
- disk interface;
- datastore.

Если VM ID исчез или перестал быть template, профиль остаётся в PostgreSQL, но
UI помечает его как broken, а spider не использует его для нового provision.

Можно иметь несколько профилей одного семейства:

```text
redos8
redos8-clean
redos8-ad
windows
windows-term
```

Сценарий выбирает нужный через `image`.

## Как spider получает backend-данные

Provision:

```text
scenario
  -> image/os profile key
  -> golden_image_profiles in PostgreSQL
  -> selected Proxmox VM ID
  -> GET /cluster/resources?type=vm
  -> GET /nodes/<node>/qemu/<vmid>/config
  -> discover node / CPU / RAM / system disk / storage
  -> OpenTofu clone
```

Для системного диска spider сначала использует порядок boot devices, если он
задан, затем выбирает первый подходящий `scsi*`, `virtio*`, `sata*` или `ide*`
диск, исключая CD-ROM и cloud-init drive.

При `resources.disk_gb` spider сравнивает запрос с **фактическим** размером
системного диска template. Значение меньше baseline отклоняется до запуска
OpenTofu.

## Подготовка golden template

Для каждого используемого профиля нужен Proxmox QEMU template.

Минимальные требования:

- CPU/RAM/сеть настроены как нормальный baseline;
- системный диск имеет нужный baseline, сейчас для основных образов используется
  40 GiB;
- DHCP работает;
- `qemu-guest-agent` установлен и запущен;
- guest подготовлен к клонированию: machine-id, DHCP identity и SSH host keys не
  должны приводить к конфликтам между клонами;
- Windows template должен быть generalized/clone-ready и иметь QEMU Guest Agent.

Размер 40 GiB остаётся нашим правилом подготовки образов, но spider не использует
зашитую константу как источник истины: фактический размер всегда читается из
Proxmox.

## API user и token

Для clone/start/read/destroy можно начать с отдельной роли:

```bash
pveum role add ArachneClone -privs \
  "Datastore.AllocateSpace,Datastore.Audit,Sys.Audit,VM.Allocate,VM.Audit,VM.Clone,VM.Config.Options,VM.PowerMgmt"
```

Для resource overrides также нужны:

```text
VM.Config.CPU
VM.Config.Memory
VM.Config.Disk
```

Создать пользователя:

```bash
pveum user add arachne@pve --comment "Arachne provisioner"
```

Выдать роль:

```bash
pveum acl modify / -user arachne@pve -role ArachneClone
```

Создать privilege-separated token:

```bash
pveum user token add arachne@pve arachne --privsep 1
```

Выдать token ту же роль:

```bash
pveum acl modify / -token 'arachne@pve!arachne' -role ArachneClone
```

Проверка:

```bash
pveum user permissions arachne@pve
pveum user token permissions arachne@pve arachne
```

Если конкретная операция вернёт `403 Permission check failed`, добавляйте только
реально требуемую privilege. Для будущего cross-node clone может понадобиться
`VM.Migrate`.

## TLS

Production:

```dotenv
PROXMOX_VE_INSECURE=false
```

Корпоративный CA кладётся в:

```text
./certs/ca.crt
```

Compose монтирует каталог сертификатов, а Арахна использует `SSL_CERT_FILE` для
HTTP-запросов к Proxmox и provider-а OpenTofu.

Проверить API с хоста:

```bash
set -a
. ./.env
set +a

curl --fail --show-error \
  --cacert ./certs/ca.crt \
  -H "Authorization: PVEAPIToken=$PROXMOX_VE_API_TOKEN" \
  "${PROXMOX_VE_ENDPOINT%/}/api2/json/version"
```

## OpenTofu state

Каждый стенд хранит отдельные workdir/state в `TOFU_STATE_ROOT/<name>`.
В Docker Compose `TOFU_STATE_ROOT` находится в persistent volume, поэтому restart
контейнера не теряет управляемое состояние VM.

## Destroy и смена Golden Image

При provision VM artifact сохраняет backend metadata исходного template.
`managed_machines` хранит эти metadata в PostgreSQL.

Поэтому если администратор завтра переключит профиль `redos8` с VM 9002 на VM
9100, уже созданный вчера стенд всё равно уничтожается с исходными lifecycle
данными. Для нового provision используется уже новый template.

Ручное удаление:

```yaml
- id: cleanup
  spider: tofu-proxmox
  action: destroy
  with:
    name: redvrm-test-001
    os: redos8
```

`resources`, `lifetime` и backend-параметры повторять не требуется.

## TTL

При `lifetime` Арахна сохраняет абсолютный `expires_at` в PostgreSQL.
Общий APScheduler раз в минуту подбирает просроченные `managed_machines` и вызывает
обычный `tofu-proxmox destroy`.

```text
running
  -> expires_at
  -> destroying
  -> destroyed
```

Failed destroy переходит в `reap_failed` и ретраится. Claim имеет lease, поэтому
падение Арахны посреди cleanup не создаёт бессмертную VM. Restart приложения не
сбрасывает TTL.

## Что не надо писать в scenario или env

Не переносите туда:

```text
VM ID template
node
system disk interface
datastore
размер golden disk
CPU/RAM golden image
OpenTofu provider internals
```

Пользовательский сценарий описывает только желаемую машину. Golden Image меню
описывает только соответствие человеческого профиля конкретному template. Всё
остальное spider обязан узнать сам.
