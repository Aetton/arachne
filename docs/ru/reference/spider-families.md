# Семейства пауков: Weave, Brood, Command

Arachne делит пауков по смыслу операции, а не по конкретному backend.

| Семейство | Что делает | Примеры |
|---|---|---|
| `Weave` | создаёт артефакты | Forgejo/GitLab workflow, package builder |
| `Brood` | создаёт вычислительное окружение | OpenTofu/Proxmox, oVirt, cloud provisioner |
| `Command` | выполняет действия на созданном окружении | Ansible, SSH, WinRM, test runner |

## Терминология DSL

Публичный DSL использует только доменные имена:

```text
weave
brood
command
```

Для явного указания семейства шага используется `family`:

```yaml
- id: stand
  spider: tofu-proxmox
  family: brood
  action: brood
```

Обычно `family` можно не писать: редактор и runtime берут его из зарегистрированного spider.

Поле `kind` не является частью нового публичного DSL. Старые сохранённые сценарии с
`kind: build` или `kind: provision` продолжают исполняться как compatibility input,
но редактор больше не должен предлагать эти значения.

Канонические действия для основных семейств:

```text
Weave   -> action: weave
Brood   -> action: brood
Command -> action: command
```

Backend-specific lifecycle actions могут существовать рядом, например `destroy` у
`tofu-proxmox`.

Старые `build`, `provision`, `run` и `deploy` могут временно приниматься конкретными
spider-ами как aliases, но новая документация и редактор их не используют как основной путь.

## Wire compatibility

Внутри транспорта пока остаются старые subject kinds:

```text
build
provision
```

Они нужны только для совместимости с существующими NATS subjects и удалёнными
responders. Пользователь сценария не должен их знать и не должен писать их вручную.

## Brood Target v1

Главная граница проходит между `Brood` и `Command`: command-spider не должен знать,
каким backend был создан target. Он получает стандартный structured artifact.

Контракт:

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

Command-spider может полагаться на `identity`, `platform`, `network`, `access`,
`lifecycle` и `backend.spider`. `backend.data` является opaque payload конкретного
Brood-spider и не используется для общей логики.

### Credentials

Секреты не кладутся в artifact открытым текстом. Используется только ссылка:

```yaml
access:
  credentials:
    type: secret_ref
    ref: machine/1234/ssh
```

## Brood -> Command

Новый рекомендуемый сценарий:

```yaml
steps:
  - id: stand
    spider: tofu-proxmox
    action: brood
    with:
      name: test-001
      os: redos8
      lifetime: 30m

  - id: deploy
    spider: ansible-local
    action: command
    with:
      target: "${stand.artifact}"
      playbook: install.yml
```

`ansible-local` раскрывает Brood artifact в стабильные scalar vars:

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

Плоские `${stand.ip}` и старые action aliases пока сохраняются для совместимости.

## Требование к новым паукам

Новые plugins наследуются от:

```python
WeaveSpider
BroodSpider
CommandSpider
```

`BuildSpider` и `ProvisionSpider` существуют только как compatibility aliases.

Новый Brood-spider должен выпускать `arachne.brood-target/v1` либо достаточно данных
для compatibility normalizer. Для новых реализаций нормальный путь — прямой выпуск v1.
