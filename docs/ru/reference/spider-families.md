# Семейства пауков: Weave, Brood, Command

Arachne делит пауков по смыслу операции, а не по конкретному backend.

| Семейство | Что делает | Примеры |
|---|---|---|
| `Weave` | создаёт артефакты | Forgejo/GitLab build, package builder |
| `Brood` | создаёт вычислительное окружение | OpenTofu/Proxmox, oVirt, cloud provisioner |
| `Command` | выполняет действия на созданном окружении | Ansible, SSH, WinRM, test runner |

Главная граница проходит между `Brood` и `Command`: command-spider не должен знать,
каким backend был создан target. Он получает стандартный structured artifact.

## Brood Target v1

Контракт называется:

```text
arachne.brood-target/v1
```

Минимальная форма metadata:

```yaml
contract: arachne.brood-target/v1

identity:
  name: test-001
  id: "1234"
  kind: vm

platform:
  os: redos8
  family: linux
  arch: x86_64

network:
  primary_ip: 10.81.19.57
  addresses:
    - 10.81.19.57

access:
  preferred: ssh
  endpoints:
    ssh:
      host: 10.81.19.57
      port: 22

lifecycle:
  state: running
  ephemeral: true
  lifetime: 30m

backend:
  spider: tofu-proxmox
  data:
    vm_id: "1234"
    node_name: pve01
```

### Обязательная публичная часть

Command-spider может полагаться на:

- `identity` — стабильная идентичность target;
- `platform` — ОС, семейство и архитектура;
- `network` — основной адрес и список адресов;
- `access` — предпочтительный протокол и endpoints;
- `lifecycle` — состояние и эфемерность;
- `backend.spider` — только для диагностики.

`backend.data` является opaque payload конкретного Brood-spider. Command-spider не
должен строить логику на `vm_id`, Proxmox node, datastore и других provider-specific
полях.

### Credentials

Секреты не кладутся в artifact открытым текстом. При наличии credentials используется
ссылка:

```yaml
access:
  credentials:
    type: secret_ref
    ref: machine/1234/ssh
```

Разрешённый consumer должен получать секрет через отдельный resolver. Логи и обычный
UI не должны раскрывать secret value.

## Переход со старых provision artifacts

До миграции всех Brood-spider старые `type: vm` artifacts с плоскими полями
`ip`, `os`, `conn`, `port`, `vm_id` нормализуются ядром в `Brood Target v1` перед
помещением в scenario context.

Плоские поля пока сохраняются как compatibility aliases, поэтому старые ссылки вида:

```yaml
target: "${stand.ip}"
```

продолжают работать.

Новый рекомендуемый путь:

```yaml
- id: stand
  spider: tofu-proxmox
  action: provision
  with:
    name: test-001
    os: redos8
    lifetime: 30m

- id: deploy
  spider: ansible-local
  action: deploy
  with:
    target: "${stand.artifact}"
    playbook: install.yml
```

`ansible-local` распознаёт Brood artifact и передаёт playbook скалярные переменные:

```text
target=10.81.19.57
target_host=10.81.19.57
target_port=22
target_connection=ssh
target_name=test-001
target_id=1234
target_kind=vm
target_os=redos8
target_family=linux
target_arch=x86_64
```

Так playbook может мигрировать отдельно от scenario: значение `target` остаётся
обычным адресом, хотя scenario уже передаёт целый structured artifact.

## FAMILY и KIND

`FAMILY` — доменная терминология Arachne:

```text
weave
brood
command
```

`KIND` пока остаётся старым wire-routing значением:

```text
build
provision
```

Это намеренное разделение. Оно позволяет вводить новую модель без одномоментного
изменения NATS subjects и удалённых responders. После миграции транспорта `KIND`
можно будет привести к новой терминологии отдельной версией wire protocol.

## Требование к новым паукам

Новые plugins должны наследоваться от одного из классов:

```python
WeaveSpider
BroodSpider
CommandSpider
```

`BuildSpider` и `ProvisionSpider` оставлены как compatibility aliases для старых
plugins.

Новый Brood-spider должен либо сразу вернуть `arachne.brood-target/v1`, либо как
минимум вернуть достаточно стандартных полей для compatibility normalizer. Для новых
реализаций предпочтителен прямой выпуск v1-контракта.
