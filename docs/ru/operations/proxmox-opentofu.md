# Proxmox и OpenTofu

`tofu-proxmox` создаёт временные VM клонированием заранее подготовленных золотых
шаблонов Proxmox. Базовый сценарий знает только имя стенда и логический тип ОС.
Кишки Proxmox/OpenTofu остаются backend-конфигурацией Арахны.

```yaml
- id: vm
  spider: tofu-proxmox
  action: provision
  with:
    name: redvrm-test-001
    os: redos8
```

Соответствие `redos8 -> VM ID шаблона` хранится в окружении Арахны, а не в YAML
сценариев.

## Пользовательский контракт

Golden image остаётся профилем по умолчанию. Если дополнительных ресурсов не
нужно, блок `resources` вообще отсутствует.

Для отдельного тестового запуска можно попросить больше ресурсов:

```yaml
- id: vm
  spider: tofu-proxmox
  action: provision
  with:
    name: redvrm-heavy-test
    os: redos8
    resources:
      cpu: 8
      memory_gb: 16
      disk_gb: 80
```

Все поля `resources` независимы и необязательны. Например, можно увеличить только
RAM:

```yaml
resources:
  memory_gb: 16
```

Пользователь сценария не указывает VM ID, node, datastore, disk interface, MiB или
любые параметры provider-а. Spider сам переводит пользовательский запрос в
backend-настройки.

Поддерживаются:

| Поле | Значение |
|---|---|
| `resources.cpu` | число vCPU |
| `resources.memory_gb` | RAM в GiB |
| `resources.disk_gb` | размер системного диска в GiB |

Если поле не указано, соответствующая характеристика наследуется от golden image.
Системный диск можно только увеличить. Для наших текущих golden image базовый
размер — **40 GiB**.

## Как идёт подключение

```text
Arachne
  -> tofu subprocess
  -> bpg/proxmox provider
  -> HTTPS :8006
  -> Proxmox VE API
```

Для клонирования VM SSH-доступ к узлам Proxmox не требуется. Spider передаёт
своё окружение процессу `tofu`, а provider сам читает endpoint и API token.

## 1. Подготовить золотой шаблон

Для каждого поддерживаемого `os` нужен Proxmox VM template.

Минимальные требования к шаблону:

- штатные CPU/RAM/сеть настроены в шаблоне;
- системный диск для текущих golden image — **40 GiB**;
- сеть получает адрес по DHCP;
- `qemu-guest-agent` установлен и запускается в гостевой ОС;
- шаблон подготовлен к клонированию: machine-id, DHCP identity и SSH host keys не
  должны оставаться одинаковыми на всех клонах;
- для Windows нужен работающий QEMU Guest Agent и соответствующая подготовка
  образа к клонированию.

OpenTofu не переопределяет ресурс, пока пользователь явно не запросил его в
`resources`.

Запишите для каждого шаблона:

- VM ID;
- node, на котором лежит template;
- datastore системного диска, если хотите разрешить `resources.disk_gb`;
- interface системного диска, если он отличается от стандартного `scsi0`.

Пример:

```text
redos8 template: VM 9002 on pve01, system disk scsi0 on local-lvm
```

## 2. Создать пользователя и роль Proxmox

Для clone/start/read/destroy можно начать с отдельной роли:

```bash
pveum role add ArachneClone -privs \
  "Datastore.AllocateSpace,Datastore.Audit,Sys.Audit,VM.Allocate,VM.Audit,VM.Clone,VM.Config.Options,VM.PowerMgmt"
```

Если разрешаете resource overrides, роли также нужны права на изменяемые ресурсы:

```text
VM.Config.CPU
VM.Config.Memory
VM.Config.Disk
```

Создайте технического пользователя:

```bash
pveum user add arachne@pve --comment "Arachne OpenTofu provisioner"
```

Дайте пользователю роль:

```bash
pveum acl modify / -user arachne@pve -role ArachneClone
```

Если конкретная версия Proxmox/provider вернёт `403 Permission check failed`,
добавляйте только требуемую privilege. Для cross-node clone может дополнительно
понадобиться `VM.Migrate`.

## 3. Создать отдельный API token

Используем privilege separation:

```bash
pveum user token add arachne@pve arachne --privsep 1
```

Секрет токена показывается только один раз. Сразу сохраните его в менеджер
секретов.

Дайте токену ту же роль:

```bash
pveum acl modify / -token 'arachne@pve!arachne' -role ArachneClone
```

Проверка:

```bash
pveum user permissions arachne@pve
pveum user token permissions arachne@pve arachne
```

Строка для provider-а:

```text
arachne@pve!arachne=<TOKEN_SECRET>
```

Именно целая строка кладётся в `PROXMOX_VE_API_TOKEN`.

## 4. Прописать переменные Арахны

В `.env` рядом с `docker-compose.yml`:

```dotenv
PROXMOX_VE_ENDPOINT=https://pve.example.internal:8006/
PROXMOX_VE_API_TOKEN=arachne@pve!arachne=<TOKEN_SECRET>
PROXMOX_VE_INSECURE=false

TOFU_TEMPLATE_REDOS8=9002
TOFU_TEMPLATE_REDOS8_NODE=pve01

TOFU_TEMPLATE_REDOS7=9001
TOFU_TEMPLATE_REDOS7_NODE=pve01

TOFU_TEMPLATE_WINDOWS=9003
TOFU_TEMPLATE_WINDOWS_NODE=pve02
```

Незаполненный `TOFU_TEMPLATE_*` означает, что этот `os` нельзя provision-ить.

### Resource overrides

CPU и RAM дополнительных backend-переменных не требуют.

Чтобы пользователь мог запросить увеличение системного диска, Арахна должна один
раз знать, где этот диск лежит. Это операторская настройка, в scenario она не
попадает:

```dotenv
TOFU_DEFAULT_GOLDEN_DISK_GB=40
TOFU_SYSTEM_DISK_INTERFACE=scsi0

TOFU_TEMPLATE_REDOS8_DISK_DATASTORE=local-lvm
TOFU_TEMPLATE_REDOS7_DISK_DATASTORE=local-lvm
TOFU_TEMPLATE_WINDOWS_DISK_DATASTORE=local-lvm
```

Для нестандартного шаблона можно переопределить backend-метаданные отдельно:

```dotenv
TOFU_TEMPLATE_REDOS8_DISK_GB=40
TOFU_TEMPLATE_REDOS8_DISK_INTERFACE=scsi0
```

Если пользователь запросит `disk_gb`, а datastore для этого профиля не настроен,
spider завершит шаг понятной ошибкой вместо попытки угадывать Proxmox storage.

### Target node

На single-node Proxmox `TOFU_TEMPLATE_*_NODE` используется и как target node.

Для другого узла назначения:

```dotenv
TOFU_NODE_NAME=pve02
```

### Target datastore для клона

Для cross-node clone с non-shared storage:

```dotenv
TOFU_CLONE_DATASTORE=local-lvm
```

Если shared storage подходит, оставьте переменную пустой.

## 5. TLS и корпоративный CA

Production:

```dotenv
PROXMOX_VE_INSECURE=false
```

Положите CA в:

```text
./certs/ca.crt
```

Compose монтирует `./certs/` в `/etc/ssl/certs/`, контейнер использует
`SSL_CERT_FILE=/etc/ssl/certs/ca.crt`.

## 6. Проверить API

```bash
set -a
. ./.env
set +a

curl --fail --show-error \
  --cacert ./certs/ca.crt \
  -H "Authorization: PVEAPIToken=$PROXMOX_VE_API_TOKEN" \
  "${PROXMOX_VE_ENDPOINT%/}/api2/json/version"
```

После сборки контейнера:

```bash
docker compose exec arachne tofu version
```

Проверка env без раскрытия секрета:

```bash
docker compose exec arachne sh -lc '
  test -n "$PROXMOX_VE_ENDPOINT" && echo PROXMOX_VE_ENDPOINT=ok
  test -n "$PROXMOX_VE_API_TOKEN" && echo PROXMOX_VE_API_TOKEN=ok
  test -n "$TOFU_TEMPLATE_REDOS8" && echo TOFU_TEMPLATE_REDOS8=ok
'
```

## 7. Создать стенд

Обычный:

```yaml
- id: vm
  spider: tofu-proxmox
  action: provision
  with:
    name: redvrm-test-001
    os: redos8
```

Тестовый увеличенный:

```yaml
- id: vm
  spider: tofu-proxmox
  action: provision
  with:
    name: redvrm-heavy-test
    os: redos8
    resources:
      cpu: 8
      memory_gb: 16
      disk_gb: 80
```

Lifecycle:

```text
tofu init
  -> tofu apply
  -> clone golden image
  -> apply only requested resource overrides
  -> start VM
  -> qemu guest agent reports IPv4
  -> Artifact(type=vm)
```

Artifact содержит также `requested_resources`, чтобы в истории запуска было видно,
что именно запросил сценарий.

## 8. Уничтожить стенд

Используйте то же имя:

```yaml
- id: cleanup
  spider: tofu-proxmox
  action: destroy
  with:
    name: redvrm-test-001
    os: redos8
```

`resources` при destroy повторять не нужно. State хранится отдельно для каждого
имени стенда в persistent Docker volume.

## Переменные целиком

| Переменная | Нужно | Что это |
|---|---:|---|
| `PROXMOX_VE_ENDPOINT` | да | `https://host:8006/`, без `/api2/json` |
| `PROXMOX_VE_API_TOKEN` | да | `user@realm!tokenid=secret` |
| `PROXMOX_VE_INSECURE` | нет | TLS bypass, в production `false` |
| `TOFU_TEMPLATE_REDOS7/8/WINDOWS` | для нужной ОС | VM ID golden image |
| `TOFU_TEMPLATE_*_NODE` | желательно | source node шаблона |
| `TOFU_NODE_NAME` | multi-node | target node |
| `TOFU_CLONE_DATASTORE` | при необходимости | target datastore клона |
| `TOFU_DEFAULT_GOLDEN_DISK_GB` | для disk override | базовый размер, сейчас 40 |
| `TOFU_SYSTEM_DISK_INTERFACE` | для disk override | общий system disk interface, обычно `scsi0` |
| `TOFU_TEMPLATE_*_DISK_DATASTORE` | для disk override | datastore системного диска профиля |
| `TOFU_TEMPLATE_*_DISK_GB` | редко | per-OS базовый размер |
| `TOFU_TEMPLATE_*_DISK_INTERFACE` | редко | per-OS disk interface |
| `TOFU_ROOT` | обычно нет | путь к OpenTofu modules |
| `TOFU_STATE_ROOT` | обычно нет | persistent state directory |
| `TOFU_DEV_FALLBACK` | только dev | synthetic VM fallback |

## Что не надо прокидывать в scenario YAML

Не кладите туда API token, Proxmox user/password, VM ID шаблонов, node, datastore,
disk interface или provider/OpenTofu-параметры.

Пользовательский уровень должен говорить только о желаемом стенде:

```yaml
os: redos8
resources:
  memory_gb: 16
```

Всё остальное — работа backend-а Арахны.
