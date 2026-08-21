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

В `TOFU_ROOT/stand` выполняет `tofu init`, `tofu apply` с `stand_name` и `os`,
затем читает output `vm_ip`.

Входы: `name`, `os`, `vcpus`, `ram_mb`, `disk_gb`. Ресурсы сейчас попадают только
в metadata результата и не передаются модулю как vars.

Артефакт `vm` содержит IP, hostname, ОС, архитектуру, тип подключения, порт,
ресурсы, backend и состояние. `redos7`/`redos8` используют SSH:22, `windows` —
WinRM:5985.

Если `tofu` не найден, паук **успешно** синтезирует VM с IP `10.81.19.200` — это
dev fallback.

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
