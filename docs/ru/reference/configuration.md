# Конфигурация

Arachne разделяет обычную конфигурацию и секретный материал.

- адреса сервисов, TLS flags, таймауты и runtime paths остаются в окружении;
- сервисные токены, логины, пароли и SSH-ключи хранятся через **Control -> Secrets**;
- прикладные соответствия Arachne хранятся в PostgreSQL и управляются через UI;
- bootstrap-секреты, без которых сама Arachne не может добраться до хранилища секретов, остаются вне Secrets.

`Control -> Secrets` содержит Providers, Credentials и Service bindings. Provider определяет физическое хранилище (`Vault` или encrypted DB), Credential описывает семантику секрета, binding связывает credential с Forgejo, GitLab, Proxmox или Nexus.

## Приложение и bootstrap-безопасность

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `ENV` / `APP_ENV` | пусто | `prod` и `production` включают проверку опасного JWT secret |
| `JWT_SECRET` | `dev-secret-change-me` | bootstrap/runtime ключ подписи сессионных JWT |
| `TOKEN_TTL_DAYS` | `7` | срок действия токена в днях |
| `ADMIN_PASSWORD` | `admin` | пароль администратора только при первом создании |
| `DATABASE_URL` | PostgreSQL `db:5432/arachne` | SQLAlchemy URL базы |
| `SCENARIOS_CONFIG` | `/app/config/scenarios.yaml` | seed-файл сценариев |
| `ARACHNE_MASTER_KEY_SOURCE` | `env` | откуда брать master key encrypted DB provider: `env` или `file` |
| `ARACHNE_MASTER_KEY_REF` | `ARACHNE_MASTER_KEY` | имя env-переменной или путь к mounted file |
| `VAULT_TOKEN` | пусто | типичный bootstrap ref для Vault token auth |
| `VAULT_SECRET_ID` | пусто | типичный bootstrap ref для Vault AppRole |

В production `JWT_SECRET` не может быть пустым или dev-заглушкой. `ADMIN_PASSWORD` применяется только при создании пользователя `admin` и не является механизмом смены пароля.

Master key encrypted DB, Vault token/AppRole secret-id и пароль самой PostgreSQL являются корневыми bootstrap-секретами. Их нельзя получать из того же Secret Provider, доступ к которому зависит от них. Для production предпочтительны mounted secret files.

## Control -> Secrets

### Providers

Поддерживаются:

- HashiCorp Vault KV v2;
- encrypted PostgreSQL payload с внешним master key.

### Credentials

Поддерживаются типы:

- `ssh`;
- `winrm`;
- `git-ssh`;
- `git-token`;
- `token`;
- `basic`.

Secret values в форме write-only: сохранённые значения не возвращаются браузеру. Пустое поле при редактировании сохраняет старое значение.

### Service bindings

В той же странице выбирается credential для инфраструктурных сервисов:

| Service | Credential type |
|---|---|
| Forgejo | `token` |
| GitLab | `token` |
| Proxmox VE | `token` |
| Nexus | `basic` |

При запуске Arachne binding разрешается через Secret Provider. Для старых адаптеров секрет материализуется только в runtime process environment. `.env` больше не является источником этих значений.

Изменение binding через GUI применяется к уже загруженным Forgejo/GitLab adapters без рестарта. Proxmox и дочерние процессы читают актуальное runtime environment при следующем вызове.

## Forgejo и динамические ветки

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `FORGEJO_URL` | адрес-заглушка | базовый URL Forgejo API |
| `FORGEJO_OWNER` | `example` | owner шагов без явного `with.owner` |
| `FORGEJO_VERIFY_TLS` | `true` | проверка TLS |
| `FORGEJO_DEADLINE` | `3600` | максимум ожидания Actions run, секунд |
| `FORGEJO_POLL_INTERVAL` | `2` | интервал чтения статуса и логов, секунд |
| `INPUT_SOURCE_CACHE_TTL` | `30` | кэш списка веток, секунд |

Forgejo token создаётся как credential типа `token` и назначается через `Control -> Secrets -> Service bindings`.

Токен должен читать репозитории и workflow, запускать и отменять Actions run, читать логи и артефакты. Точный набор прав зависит от версии Forgejo.

## GitLab CI

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `GITLAB_URL` | адрес-заглушка | базовый URL GitLab |
| `GITLAB_VERIFY_TLS` | `true` | проверка TLS |
| `GITLAB_DEADLINE` | `3600` | максимум ожидания pipeline, секунд |
| `GITLAB_POLL_INTERVAL` | `2` | интервал чтения статуса и job trace, секунд |

GitLab token создаётся как credential типа `token` и назначается через `Control -> Secrets -> Service bindings`.

GitLab spider создаёт pipeline через API v4, читает job trace, собирает job artifacts и умеет отменять pipeline. В шаге используется `with.project` с ID проекта или путём вида `group/subgroup/repo`; `with.repo` работает как короткий алиас. `with.ref` или `with.branch` задаёт ветку или тег. Остальные поля `with` передаются в pipeline как CI/CD variables.

Пример:

```yaml
spider: gitlab
with:
  project: group/subgroup/repo
  ref: main
  VERSION: 1.2.3
  DEBUG: false
```

Токену нужны права на чтение проекта, создание и отмену pipeline, чтение jobs, trace и artifacts.

## Proxmox / OpenTofu

В окружении остаются только обычные параметры соединения:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `PROXMOX_VE_ENDPOINT` | пусто | базовый URL Proxmox VE, например `https://pve.example:8006/` |
| `PROXMOX_VE_INSECURE` | `false` | отключение TLS verification; для production оставляйте `false` |
| `TOFU_ROOT` | `../tofu` | корень OpenTofu modules |
| `TOFU_STATE_ROOT` | `/tmp/arachne-tofu-state` в коде, persistent volume в Compose | workdir и state временных стендов |
| `TOFU_DEV_FALLBACK` | `false` | синтетическая VM только для разработки |

Proxmox API token создаётся как credential типа `token` и назначается через `Control -> Secrets -> Service bindings`. На runtime он материализуется как `PROXMOX_VE_API_TOKEN`, который используют и API client, и наследующий окружение OpenTofu provider.

Golden Image mappings не являются environment configuration. Они хранятся в PostgreSQL и управляются через:

```text
Control -> Golden Images
```

Профиль хранит человеческий key, label, OS family, выбранный Proxmox VM ID и enabled state. Source node, datastore, system disk interface, disk size, CPU и RAM читаются напрямую из Proxmox API при каждом provision.

Не добавляйте обратно переменные вида:

```text
TOFU_TEMPLATE_*
TOFU_TEMPLATE_*_NODE
TOFU_TEMPLATE_*_DISK_*
TOFU_NODE_NAME
TOFU_DEFAULT_GOLDEN_DISK_GB
TOFU_SYSTEM_DISK_INTERFACE
```

Они создают второй источник истины для данных, которыми уже владеет Proxmox.

Подробная схема: [Golden Images](/ru/operations/golden-images) и [Proxmox и OpenTofu](/ru/operations/proxmox-opentofu).

## Nexus и локальные исполнители

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `NEXUS_URL` | адрес-заглушка | endpoint и построение ссылок на Nexus |
| `ANSIBLE_PLAYBOOKS_DIR` | `../playbooks` | dev fallback каталога playbook |

Nexus login/password создаются как credential типа `basic` и назначаются через `Control -> Secrets -> Service bindings`. Runtime compatibility bridge выставляет `NEXUS_USER` и `NEXUS_PASSWORD` только внутри процесса Arachne и его дочерних процессов.

Важно: Forgejo/GitLab workflows имеют собственные secret stores. Если Nexus upload выполняется внутри удалённого CI workflow, его credential должен быть доступен этому workflow через secret manager соответствующей CI-системы. Arachne binding не пересылает секрет произвольно через workflow inputs.

## Ansible playbook repository

Обычная конфигурация находится в `Control -> Ansible`: repository URL, default ref, subdir, cache directory и Git credential. Env-переменные `ANSIBLE_PLAYBOOK_REPO_*` остаются только bootstrap defaults до первого сохранения настроек через UI.

`ANSIBLE_PLAYBOOK_CREDENTIALS_REF` содержит только ссылку на credential, а не secret material.

## Шина

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `BUS_BACKEND` | `inmemory` | `inmemory` или `nats` |
| `NATS_URL` | `nats://127.0.0.1:4222` | адрес NATS |

`inmemory` подходит для одного процесса. `nats` выносит транспорт наружу. Отдельный процесс spider-worker придётся собирать самостоятельно: готового CLI в репозитории нет.

## `ARACHNE_URL`

Переменная нужна старым callback workflow/actions из `.env.example`. Forgejo spider v16 читает состояние и логи через API, поэтому работает без `ARACHNE_URL`.

## TLS и внутренний CA

Пример Compose монтирует `./certs/` в `/etc/ssl/certs/` и задаёт:

```yaml
SSL_CERT_FILE: /etc/ssl/certs/ca.crt
REQUESTS_CA_BUNDLE: /etc/ssl/certs/ca.crt
```

Этот CA используется не только Forgejo. Proxmox API client и OpenTofu provider также должны доверять внутреннему сертификату.

Проверьте, что файл `ca.crt` действительно существует. В production лучше добавить CA, чем выставлять `FORGEJO_VERIFY_TLS=false`, `GITLAB_VERIFY_TLS=false` или `PROXMOX_VE_INSECURE=true`.

## Приоритет источников

- bootstrap secrets и runtime roots живут вне управляемого secret provider;
- обычная connection configuration остаётся в environment/DB settings;
- Vault или encrypted DB хранит управляемый secret material;
- `Control -> Secrets` хранит providers, credentials и service bindings;
- PostgreSQL хранит сценарии, ACL, Golden Image profiles и managed machines;
- Proxmox остаётся источником истины для фактической конфигурации template;
- явные параметры сценария задают желаемый результат, но не backend internals.
