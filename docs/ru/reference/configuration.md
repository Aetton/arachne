# Конфигурация

Основные несекретные настройки приходят из окружения. Compose читает `.env`, а его
`environment` переопределяет одинаковые ключи из `env_file`.

Секреты внешних систем управляются через **Control -> Secrets**. В `.env` остаются
только bootstrap roots, которые нужны самой Arachne до доступа к Secret Provider.

## Приложение и bootstrap

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `ENV` / `APP_ENV` | пусто | `prod` и `production` включают проверку опасного JWT secret |
| `JWT_SECRET` | `dev-secret-change-me` | bootstrap-ключ подписи сессионных JWT |
| `TOKEN_TTL_DAYS` | `7` | срок действия токена в днях |
| `ADMIN_PASSWORD` | `admin` | пароль администратора при первом создании |
| `DATABASE_URL` | PostgreSQL `db:5432/arachne` | SQLAlchemy URL базы |
| `POSTGRES_PASSWORD` | задаётся deployment | bootstrap password PostgreSQL |
| `ARACHNE_MASTER_KEY_SOURCE` | `env` | источник master key для encrypted DB provider: `env` или `file` |
| `ARACHNE_MASTER_KEY_REF` | `ARACHNE_MASTER_KEY` | имя env или путь к mounted file с master key |
| `VAULT_TOKEN` / `VAULT_SECRET_ID` | пусто | bootstrap auth Vault, если provider ссылается на эти env refs |
| `SCENARIOS_CONFIG` | `/app/config/scenarios.yaml` | seed-файл сценариев |

`ADMIN_PASSWORD` применяется только при создании пользователя `admin`. После этого
паролем управляет база. Master key и Vault bootstrap secret нельзя хранить в самом
`Control -> Secrets`, иначе хранилище потребует собственный секрет для доступа к себе.

## Control -> Secrets

Раздел содержит два уровня:

- **Providers**: HashiCorp Vault KV v2 или encrypted DB;
- **Credentials**: семантические наборы доступа (`ssh`, `winrm`, `git-ssh`, `git-token`, `token`, `basic`).

Secret values после сохранения обратно в браузер не выводятся. Пустое secret-поле
при редактировании credential означает «оставить текущее значение».

### Service bindings

Forgejo, GitLab, Proxmox VE и Nexus привязываются к credentials в секции
**Infrastructure bindings**. Binding хранит только credential key.

| Service | Credential type |
|---|---|
| Forgejo | `token` |
| GitLab | `token` |
| Proxmox VE | `token` |
| Nexus | `basic` |

Старые adapters пока используют привычные environment variable names внутри процесса,
но значения материализуются из Secret Provider во время работы Arachne. `.env` больше
не является владельцем этих credentials.

## Forgejo и динамические ветки

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `FORGEJO_URL` | адрес-заглушка | базовый URL Forgejo API |
| `FORGEJO_OWNER` | `example` | owner шагов без явного `with.owner` |
| `FORGEJO_VERIFY_TLS` | `true` | проверка TLS |
| `FORGEJO_DEADLINE` | `3600` | максимум ожидания Actions run, секунд |
| `FORGEJO_POLL_INTERVAL` | `2` | интервал чтения статуса и логов, секунд |
| `INPUT_SOURCE_CACHE_TTL` | `30` | кэш списка веток, секунд |

Токен выбирается в `Control -> Secrets -> Infrastructure bindings` и должен уметь
читать репозитории/workflow, запускать и отменять Actions run, читать логи и артефакты.

## GitLab CI

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `GITLAB_URL` | адрес-заглушка | базовый URL GitLab |
| `GITLAB_VERIFY_TLS` | `true` | проверка TLS |
| `GITLAB_DEADLINE` | `3600` | максимум ожидания pipeline, секунд |
| `GITLAB_POLL_INTERVAL` | `2` | интервал чтения статуса и job trace, секунд |

GitLab token выбирается в `Control -> Secrets -> Infrastructure bindings`.

## Proxmox / OpenTofu

В окружении остаются только несекретные параметры соединения:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `PROXMOX_VE_ENDPOINT` | пусто | базовый URL Proxmox VE |
| `PROXMOX_VE_INSECURE` | `false` | отключение TLS verification; для production оставляйте `false` |
| `TOFU_ROOT` | `../tofu` | корень OpenTofu modules |
| `TOFU_STATE_ROOT` | `/tmp/arachne-tofu-state` в коде, persistent volume в Compose | workdir и state временных стендов |
| `TOFU_DEV_FALLBACK` | `false` | синтетическая VM только для разработки |

Proxmox API token выбирается в `Control -> Secrets -> Infrastructure bindings`.
Golden Image mappings хранятся в PostgreSQL и управляются через `Control -> Golden Images`.

## Ansible playbook repository

Настройки repository управляются через `Control -> Ansible`. Репозиторий может
использовать credential типа `git-ssh` или `git-token` из `Control -> Secrets`.

`ANSIBLE_PLAYBOOK_CREDENTIALS_REF` допустим только как bootstrap credential key.
Secret material эта переменная не содержит.

## Brood -> Ansible target access

Brood target contract содержит endpoint и ссылку на credential:

```yaml
access:
  preferred: ssh
  endpoints:
    ssh:
      host: 10.81.19.210
      port: 22
  credentials:
    type: secret_ref
    ref: redos8-default
```

`ansible-local` автоматически обнаруживает Brood Artifact среди входов шага и
создаёт временный inventory. Credential разрешается из `Control -> Secrets` только
перед запуском `ansible-playbook`.

Поддерживаются:

- `ssh` + private key;
- `ssh` + password;
- `winrm` + password.

Runtime directory создаётся с mode `0700`, inventory/key/known_hosts files с `0600`.
`credentials_ref` не передаётся playbook как extra-var, secret values не попадают в
command line или RunOutput. После завершения run временный каталог удаляется.

Для SSH password auth container содержит `sshpass`; для WinRM установлен `pywinrm`.

## Nexus

`NEXUS_URL` остаётся обычной конфигурацией для построения ссылок. `NEXUS_USER` и
`NEXUS_PASSWORD` в `.env` больше не хранятся: credential типа `basic` выбирается
через Infrastructure bindings.

Если upload выполняется внутри удалённого Forgejo/GitLab workflow, этот workflow
должен получать Nexus secret из secret store своей CI-системы. Arachne намеренно не
проталкивает пароль через workflow inputs.

## Шина

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `BUS_BACKEND` | `inmemory` | `inmemory` или `nats` |
| `NATS_URL` | `nats://127.0.0.1:4222` | адрес NATS |

## TLS и внутренний CA

В production лучше добавить корпоративный CA в trust store контейнера, чем отключать
TLS verification у Forgejo, GitLab или Proxmox.

## Приоритет источников

- `.env` хранит bootstrap roots, connection config и runtime paths;
- `Control -> Secrets` хранит управляемые service/target credentials;
- PostgreSQL хранит сценарии, ACL, Golden Image profiles, bindings и managed machines;
- Proxmox остаётся источником истины для фактической конфигурации template;
- Brood target contract является источником endpoint + credentials_ref для Command spiders;
- explicit scenario params задают желаемый результат, но не secret material.
