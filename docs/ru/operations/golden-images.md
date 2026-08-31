# Golden Images

Golden Image — это человеческий профиль, который связывает сценарии Arachne с конкретным Proxmox QEMU template.

Главное правило слоя:

> Сценарий описывает желаемую машину. Golden Image хранит выбор шаблона. Spider сам узнаёт инфраструктурные детали у Proxmox.

В `.env` не должны жить VM ID шаблонов, node, datastore, disk interface, размер диска или ресурсы golden image. Эти данные уже есть в Proxmox и читаются live.

## Где находится меню

Администратор открывает:

```text
Control -> Golden Images
```

Страница показывает сохранённые профили карточками и отдельно список доступных Proxmox templates.

Для каждой карточки Arachne пытается получить живое состояние выбранного template и показывает:

- красивое имя профиля;
- стабильный ключ профиля;
- семейство ОС;
- имя Proxmox template;
- VM ID;
- node;
- CPU;
- RAM;
- системный диск;
- disk interface;
- datastore;
- состояние профиля: ready, disabled или broken.

Node, CPU, RAM и диск являются read-only данными. Они не редактируются в Arachne.

## Что хранится в PostgreSQL

Профиль Golden Image хранит только соответствие между пользовательским именем и Proxmox template:

```text
slug
label
os
template_vm_id
enabled
```

Пример:

```text
label:          RedOS 8
slug:           redos8
os:             redos8
template_vm_id: 9002
enabled:        true
```

Это не копия конфигурации VM. PostgreSQL не является источником истины для node, storage, CPU, RAM или диска.

## Создание первого профиля

Перед началом убедитесь, что `.env` содержит рабочее подключение к Proxmox:

```dotenv
PROXMOX_VE_ENDPOINT=https://pve.example.internal:8006/
PROXMOX_VE_API_TOKEN=arachne@pve!arachne=<TOKEN_SECRET>
PROXMOX_VE_INSECURE=false
```

После запуска Arachne:

1. откройте **Control -> Golden Images**;
2. убедитесь, что список templates загрузился;
3. нажмите создание профиля;
4. задайте красивое имя, например `RedOS 8`;
5. задайте ключ `redos8`;
6. выберите семейство ОС `redos8`;
7. выберите нужный Proxmox template;
8. сохраните профиль.

После сохранения карточка должна перейти в состояние `ready` и показать фактические характеристики VM.

## Ключ профиля и сценарии

Самый простой сценарий:

```yaml
with:
  name: test-001
  os: redos8
```

Если `image` не указан, spider ищет Golden Image с ключом, равным `os`. Поэтому профиль `redos8` является профилем по умолчанию для `os: redos8`.

Если одного образа на семейство ОС мало, создайте несколько профилей:

```text
redos8
redos8-clean
redos8-ad
redos8-debug
windows
windows-term
```

Тогда сценарий может выбрать конкретный:

```yaml
with:
  name: clean-test
  os: redos8
  image: redos8-clean
```

`os` продолжает определять семейство гостя и тип подключения, а `image` выбирает конкретный Golden Image профиль.

## Что происходит при provision

Spider не берёт node или disk metadata из env. Перед `tofu apply` он делает discovery:

```text
scenario
  -> image или os
  -> Golden Image profile в PostgreSQL
  -> template_vm_id
  -> Proxmox /cluster/resources?type=vm
  -> source node
  -> /nodes/<node>/qemu/<vmid>/config
  -> CPU / RAM / disks / storage
  -> OpenTofu
```

Таким образом, если template переехал на другой node или у него изменился datastore, Arachne увидит новое состояние без изменения конфигурации портала.

## Как определяется системный диск

Для resource override `disk_gb` нужен системный диск исходного template.

Spider:

1. учитывает порядок boot devices, если он задан;
2. рассматривает обычные QEMU disk interfaces (`scsi*`, `virtio*`, `sata*`, `ide*`);
3. исключает CD-ROM и cloud-init drive;
4. извлекает datastore и фактический размер выбранного диска.

Если пользователь просит:

```yaml
resources:
  disk_gb: 80
```

а template реально имеет системный диск 40 GiB, рост разрешён.

Если пользователь просит 20 GiB, spider отклоняет запрос до OpenTofu. Baseline берётся не из константы и не из `.env`, а из текущего Proxmox config.

## Подготовка template

Golden Image должен быть полноценным QEMU template, пригодным для клонирования.

Для RedOS/Linux:

- системный диск подготовлен с нужным baseline;
- сеть получает адрес по DHCP;
- установлен и работает `qemu-guest-agent`;
- machine-id подготовлен к клонированию;
- DHCP identity не должна конфликтовать между клонами;
- SSH host keys не должны приводить к одинаковой идентичности всех потомков.

Для Windows дополнительно нужен clone-ready/generalized образ и рабочий QEMU Guest Agent.

Текущий организационный baseline основных golden images — 40 GiB системного диска. Это требование к подготовке образа, а не конфигурационная константа spider-а.

## Состояния профиля

### Ready

Выбранный VM ID существует, объект является template, API доступен, конфигурация читается.

Такой профиль можно использовать для нового provision.

### Disabled

Профиль сохранён, но выключен администратором.

Он не должен предлагаться как нормальный вариант для новых запусков.

### Broken

Профиль существует в PostgreSQL, но live discovery не подтверждает пригодный template.

Типовые причины:

- VM удалена;
- VM ID изменился;
- объект перестал быть template;
- токен больше не видит объект;
- Proxmox API недоступен;
- node/config endpoint возвращает ошибку.

Broken profile не удаляется автоматически. Это намеренно: администратор должен видеть, какое соответствие сломалось, а не обнаруживать исчезновение конфигурации постфактум.

## Замена golden image

Новый образ можно ввести без изменения сценариев.

Например, было:

```text
redos8 -> VM 9002
```

Создайте новый template 9100, проверьте его, затем в Golden Images переключите профиль `redos8` на 9100.

Новые provision используют 9100.

Уже созданные машины не теряют возможность удаления. При создании stand Arachne сохраняет backend metadata конкретной VM в `managed_machines`, поэтому destroy старого стенда не зависит от текущего значения Golden Image mapping.

## TTL и Golden Images

Golden Image отвечает за рождение машины, но не за срок её жизни.

Сценарий может задать:

```yaml
with:
  name: quick-test
  os: redos8
  lifetime: 30m
```

После provision Arachne сохраняет `expires_at` в PostgreSQL. Lifecycle reaper раз в минуту подбирает просроченные машины и вызывает обычный destroy.

Смена Golden Image профиля во время жизни VM не меняет её TTL и не мешает cleanup.

## Resource overrides

Golden image остаётся baseline. Если `resources` не указан, clone наследует его конфигурацию.

Можно изменить только нужное:

```yaml
resources:
  cpu: 8
```

или:

```yaml
resources:
  memory_gb: 16
```

или:

```yaml
resources:
  disk_gb: 80
```

CPU, RAM и disk override независимы. Незапрошенные характеристики не должны переопределяться OpenTofu.

## Проверка после настройки

Для первого профиля рекомендуется пройти короткий интеграционный цикл:

1. открыть Golden Images и убедиться, что карточка `ready`;
2. проверить отображаемые VM ID/node/CPU/RAM/disk/storage против Proxmox;
3. создать обычный clone без overrides;
4. убедиться, что clone наследовал baseline;
5. вручную уничтожить его;
6. создать VM с `lifetime: 2m`;
7. проверить `managed_machines.expires_at`;
8. дождаться автоматического destroy;
9. проверить отдельно CPU, RAM и disk overrides;
10. переключить профиль на другой template и убедиться, что старый stand всё ещё удаляется.

## Что не надо делать

Не возвращайте старую схему через новые переменные окружения вроде:

```text
TOFU_TEMPLATE_REDOS8
TOFU_TEMPLATE_REDOS8_NODE
TOFU_TEMPLATE_REDOS8_DISK_DATASTORE
TOFU_SYSTEM_DISK_INTERFACE
TOFU_DEFAULT_GOLDEN_DISK_GB
```

Это создаёт второй источник истины и снова требует ручной синхронизации с Proxmox.

Если данные можно получить из API инфраструктуры, spider должен получать их из API.

## Связанные страницы

- [Proxmox и OpenTofu](/ru/operations/proxmox-opentofu)
- [Конфигурация](/ru/reference/configuration)
- [Паук `tofu-proxmox`](/ru/reference/spiders#tofu-proxmox)
- [Синтаксис сценариев](/ru/reference/scenario-syntax)
- [Диагностика](/ru/operations/troubleshooting)
