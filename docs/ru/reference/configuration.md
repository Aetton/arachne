# Конфигурация

Основные настройки приходят из окружения. Compose читает `.env`, а его
`environment` переопределяет одинаковые ключи из `env_file`.

Важно разделять два типа конфигурации:

- **доступ к внешней системе** хранится в окружении;
- **прикладные соответствия внутри Arachne** хранятся в PostgreSQL и управляются через UI.

Для Proxmox это означает: endpoint и API token лежат в `.env`, а Golden Image profiles настраиваются через **Control -> Golden Images**. VM ID шаблона, node, datastore и параметры дисков в env не дублируются.

## Приложение и безопасность

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `ENV` / `APP_ENV` | пусто | `prod` и `production` включают проверку опасного JWT secret |
| `JWT_SECRET` | `dev-secret-change-me` | ключ подписи сессионных JWT |
| `TOKEN_TTL_DAYS` | `7` | срок действия токена в днях |
| `ADMIN_PASSWORD` | `admin` | пароль администратора при первом создании |
| `DATABASE_URL` | PostgreSQL `db:5432/arachne` | SQLAlchemy URL базы |
| `SCENARIOS_CONFIG` | `/app/config/scenarios.yaml` | seed-файл сценариев |

В production `JWT_SECRET` не может быть пустым, `dev-secret-change-me` или
`change-me-in-prod`. Приложение упадёт при старте. `ADMIN_PASSWORD` применяется
только при создании пользователя `admin` и не является механизмом смены пароля.

## Forgejo и динамические ветки

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `FORGEJO_URL` | адрес-заглушка | базовый URL Forgejo API |
| `FORGEJO_TOKEN` | пусто | токен сервисной учётной записи |
| `FORGEJO_OWNER` | `example` | owner шагов без явного `with.owner` |
| `FORGEJO_VERIFY_TLS` | `true` | проверка TLS |
| `FORGEJO_DEADLINE` | `3600` | максимум ожидания Actions run, секунд |
| `FORGEJO_POLL_INTERVAL` | `2` | интервал чтения статуса и логов, секунд |
| `INPUT_SOURCE_CACHE_TTL` | `30` | кэш списка веток, секунд |

Токен должен читать репозитории и workflow, запускать и отменять Actions run,
читать логи и артефакты. Точный набор прав зависит от версии Forgejo.

## GitLab CI

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `GITLAB_URL` | адрес-заглушка | базовый URL GitLab |
| `GITLAB_TOKEN` | пусто | токен сервисной учётной записи |
| `GITLAB_VERIFY_TLS` | `true` | проверка TLS |
| `GITLAB_DEADLINE` | `3600` | максимум ожидания pipeline, секунд |
| `GITLAB_POLL_INTERVAL` | `2` | интервал чтения статуса и job trace, секунд |

GitLab spider создаёт pipeline через API v4, читает job trace, собирает job artifacts
и умеет отменять pipeline. В шаге используется `with.project` с ID проекта или путём
вида `group/subgroup/repo`; `with.repo` работает как короткий алиас. `with.ref` или
`with.branch` задаёт ветку или тег. Остальные поля `with` передаются в pipeline как
CI/CD variables.

Пример:

```yaml
spider: gitlab
with:
  project: group/subgroup/repo
  ref: main
  VERSION: 1.2.3
  DEBUG: false
```

Токену нужны права на чтение проекта, создание и отмену pipeline, чтение jobs,
trace и artifacts. Если в GitLab запрещены pipeline variables для роли сервисной
учётки, разрешите их или переведите конкретный pipeline на GitLab inputs.

## Proxmox / OpenTofu

В окружении остаются только параметры соединения:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `PROXMOX_VE_ENDPOINT` | пусто | базовый URL Proxmox VE, например `https://pve.example:8006/` |
| `PROXMOX_VE_API_TOKEN` | пусто | API token в формате `user@realm!tokenid=secret` |
| `PROXMOX_VE_INSECURE` | `false` | отключение TLS verification; для production оставляйте `false` |
| `TOFU_ROOT` | `../tofu` | корень OpenTofu modules |
| `TOFU_STATE_ROOT` | `/tmp/arachne-tofu-state` в коде, persistent volume в Compose | workdir и state временных стендов |
| `TOFU_DEV_FALLBACK` | `false` | синтетическая VM только для разработки |

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

## Артефакты и локальные исполнители

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `NEXUS_URL` | адрес-заглушка | построение ссылок на Nexus |
| `NEXUS_USER` | пусто | используется playbook/workflow, не порталом напрямую |
| `NEXUS_PASSWORD` | пусто | то же; храните как секрет |
| `ANSIBLE_PLAYBOOKS_DIR` | `../playbooks` | каталог playbook |

## Шина

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `BUS_BACKEND` | `inmemory` | `inmemory` или `nats` |
| `NATS_URL` | `nats://127.0.0.1:4222` | адрес NATS |

`inmemory` подходит для одного процесса. `nats` выносит транспорт наружу. Отдельный
процесс spider-worker придётся собирать самостоятельно: готового CLI в репозитории нет.

## `ARACHNE_URL`

Переменная нужна старым callback workflow/actions из `.env.example`. Forgejo spider
v16 читает состояние и логи через API, поэтому работает без `ARACHNE_URL`.

## TLS и внутренний CA

Пример Compose монтирует `./certs/` в `/etc/ssl/certs/` и задаёт:

```yaml
SSL_CERT_FILE: /etc/ssl/certs/ca.crt
REQUESTS_CA_BUNDLE: /etc/ssl/certs/ca.crt
```

Этот CA используется не только Forgejo. Proxmox API client и OpenTofu provider также должны доверять внутреннему сертификату.

Проверьте, что файл `ca.crt` действительно существует. В production лучше добавить
CA, чем выставлять `FORGEJO_VERIFY_TLS=false`, `GITLAB_VERIFY_TLS=false` или `PROXMOX_VE_INSECURE=true`.

## Приоритет источников

- environment хранит connection/auth и runtime paths;
- PostgreSQL хранит управляемые сущности Arachne: сценарии, ACL, Golden Image profiles и managed machines;
- Proxmox является источником истины для фактической конфигурации template;
- явные параметры сценария задают желаемый результат, но не backend internals;
- после bootstrap база важнее YAML seed-файла сценариев.
