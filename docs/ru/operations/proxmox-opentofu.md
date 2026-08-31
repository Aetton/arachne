# Proxmox и OpenTofu

`tofu-proxmox` создаёт временные VM клонированием заранее подготовленных золотых
шаблонов Proxmox. Сценарий Арахны не описывает CPU, RAM, диски и сеть: всё это
приходит из шаблона.

Обычный сценарий знает только имя стенда и логический тип ОС:

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

- нужные штатные CPU/RAM/сеть уже настроены в шаблоне;
- системный диск для наших золотых образов — **40 GiB**;
- сеть получает адрес по DHCP;
- `qemu-guest-agent` установлен и запускается в гостевой ОС;
- шаблон подготовлен к клонированию: уникальные machine-id, DHCP identity и SSH
  host keys не должны оставаться одинаковыми на всех клонах;
- для Windows нужен работающий QEMU Guest Agent и соответствующая подготовка
  образа к клонированию.

OpenTofu не переопределяет CPU, RAM, диски или network devices. Это сделано
намеренно: golden image остаётся источником правды.

Имя VM в Proxmox будет равно `with.name`. Guest hostname отдельно сейчас не
меняется; downstream шаги должны использовать IP из VM artifact. Если нужен
hostname внутри ОС, задавайте его отдельным provisioning шагом.

Запишите для каждого шаблона:

- VM ID;
- node, на котором лежит template.

Например:

```text
redos8 template: VM 9002 on pve01
redos7 template: VM 9001 on pve01
windows template: VM 9003 on pve02
```

## 2. Создать пользователя и роль Proxmox

Не используйте `root@pam` и не выдавайте `Administrator` без необходимости.
Для обычного clone/start/read/destroy пути можно начать с отдельной роли:

```bash
pveum role add ArachneClone -privs \
  "Datastore.AllocateSpace,Datastore.Audit,Sys.Audit,VM.Allocate,VM.Audit,VM.Clone,VM.Config.Options,VM.PowerMgmt"
```

Создайте технического пользователя:

```bash
pveum user add arachne@pve --comment "Arachne OpenTofu provisioner"
```

Дайте пользователю роль:

```bash
pveum acl modify / -user arachne@pve -role ArachneClone
```

Этот набор прав рассчитан на наш текущий путь: полный клон готового VM template,
включение guest agent, старт, чтение состояния и удаление VM. Если конкретная
версия Proxmox/provider вернёт `403 Permission check failed`, добавляйте только
привилегию, названную в ошибке. Для cross-node clone может дополнительно
понадобиться `VM.Migrate`; при изменении дисковой конфигурации — `VM.Config.Disk`.

Provider `bpg/proxmox` публикует более широкий пример Terraform-роли, но сам
предупреждает, что этот список избыточен для большинства задач.

## 3. Создать отдельный API token

Используем privilege separation, чтобы токен имел собственный ACL:

```bash
pveum user token add arachne@pve arachne --privsep 1
```

**Секрет токена показывается только один раз. Сразу сохраните его в менеджер
секретов.**

Дайте токену ту же роль:

```bash
pveum acl modify / -token 'arachne@pve!arachne' -role ArachneClone
```

Проверить эффективные права:

```bash
pveum user permissions arachne@pve
pveum user token permissions arachne@pve arachne
```

Строка для `bpg/proxmox` имеет формат:

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

### Target node

На single-node Proxmox ничего больше не нужно: `TOFU_TEMPLATE_*_NODE`
используется и как target node.

Если клон должен создаваться на другом узле:

```dotenv
TOFU_NODE_NAME=pve02
```

Тогда `TOFU_TEMPLATE_*_NODE` остаётся source node шаблона, а `TOFU_NODE_NAME` —
узел назначения.

### Target datastore

По умолчанию storage placement наследуется от template. Для cross-node clone с
non-shared storage можно явно указать:

```dotenv
TOFU_CLONE_DATASTORE=local-lvm
```

Если shared storage уже подходит, оставьте переменную пустой.

## 5. TLS и корпоративный CA

Production-вариант:

```dotenv
PROXMOX_VE_INSECURE=false
```

Положите CA, которым подписан сертификат Proxmox, в:

```text
./certs/ca.crt
```

Compose уже монтирует `./certs/` в `/etc/ssl/certs/`, а контейнер использует
`SSL_CERT_FILE=/etc/ssl/certs/ca.crt`.

`PROXMOX_VE_INSECURE=true` допустим только для лабораторной диагностики.

## 6. Проверить API до запуска сценария

С хоста, где лежит `.env`:

```bash
set -a
. ./.env
set +a

curl --fail --show-error \
  --cacert ./certs/ca.crt \
  -H "Authorization: PVEAPIToken=$PROXMOX_VE_API_TOKEN" \
  "${PROXMOX_VE_ENDPOINT%/}/api2/json/version"
```

Не печатайте `PROXMOX_VE_API_TOKEN` в CI-лог.

После сборки контейнера:

```bash
docker compose exec arachne tofu version
```

Проверить, что обязательные переменные реально попали внутрь, не раскрывая
секрет:

```bash
docker compose exec arachne sh -lc '
  test -n "$PROXMOX_VE_ENDPOINT" && echo PROXMOX_VE_ENDPOINT=ok
  test -n "$PROXMOX_VE_API_TOKEN" && echo PROXMOX_VE_API_TOKEN=ok
  test -n "$TOFU_TEMPLATE_REDOS8" && echo TOFU_TEMPLATE_REDOS8=ok
'
```

## 7. Создать VM из Арахны

```yaml
- id: vm
  spider: tofu-proxmox
  action: provision
  with:
    name: redvrm-test-001
    os: redos8
```

Spider выполнит примерно такой lifecycle:

```text
tofu init
  -> tofu apply
  -> clone VM template
  -> start VM
  -> qemu guest agent reports IPv4
  -> Artifact(type=vm)
```

Основные поля artifact:

```yaml
type: vm
location: "<vm-id>"
metadata:
  os: redos8
  ip: 10.x.x.x
  conn: ssh
  port: 22
  vm_id: "1234"
  template_vm_id: 9002
  node_name: pve01
  state: running
```

Для Windows `conn=winrm`, `port=5985`.

## 8. Уничтожить стенд

State хранится отдельно для каждого имени стенда в persistent Docker volume.
Поэтому `destroy` должен использовать **то же имя**, что и `provision`:

```yaml
- id: cleanup
  spider: tofu-proxmox
  action: destroy
  with:
    name: redvrm-test-001
    os: redos8
```

Если state потерян, spider намеренно не пытается угадывать VM по имени и удалять
её напрямую через API.

## Переменные целиком

| Переменная | Нужно | Что это |
|---|---:|---|
| `PROXMOX_VE_ENDPOINT` | да | `https://host:8006/`, без `/api2/json` |
| `PROXMOX_VE_API_TOKEN` | да | `user@realm!tokenid=secret` |
| `PROXMOX_VE_INSECURE` | нет | `false` по умолчанию; не отключать TLS в production |
| `TOFU_TEMPLATE_REDOS7` | для redos7 | VM ID golden template |
| `TOFU_TEMPLATE_REDOS8` | для redos8 | VM ID golden template |
| `TOFU_TEMPLATE_WINDOWS` | для windows | VM ID golden template |
| `TOFU_TEMPLATE_REDOS7_NODE` | желательно | source node шаблона |
| `TOFU_TEMPLATE_REDOS8_NODE` | желательно | source node шаблона |
| `TOFU_TEMPLATE_WINDOWS_NODE` | желательно | source node шаблона |
| `TOFU_NODE_NAME` | multi-node | target node для новых VM |
| `TOFU_CLONE_DATASTORE` | при необходимости | target datastore полного клона |
| `TOFU_ROOT` | обычно нет | путь к OpenTofu modules |
| `TOFU_STATE_ROOT` | обычно нет | persistent state directory |
| `TOFU_DEV_FALLBACK` | только dev | разрешить синтетическую VM без `tofu` |

## Что не надо прокидывать в scenario YAML

Не кладите туда:

- API token;
- Proxmox username/password;
- VM ID золотых шаблонов;
- node/datastore инфраструктуры;
- CPU/RAM/disk параметры золотого образа.

Эти данные относятся к backend-конфигурации Арахны. Сценарий должен оставаться
переносимым и говорить только: «дай мне стенд такого типа».
