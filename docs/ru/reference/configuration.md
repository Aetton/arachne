# Конфигурация

Основные настройки приходят из окружения. Compose читает `.env`, а его
`environment` переопределяет одинаковые ключи из `env_file`.

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

## Артефакты и локальные исполнители

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `NEXUS_URL` | адрес-заглушка | построение ссылок на Nexus |
| `NEXUS_USER` | пусто | используется playbook/workflow, не порталом напрямую |
| `NEXUS_PASSWORD` | пусто | то же; храните как секрет |
| `ANSIBLE_PLAYBOOKS_DIR` | `../playbooks` | каталог playbook |
| `TOFU_ROOT` | `../tofu` | корень модулей OpenTofu |

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

Проверьте, что файл `ca.crt` действительно существует. В production лучше добавить
CA, чем выставлять `FORGEJO_VERIFY_TLS=false` или `GITLAB_VERIFY_TLS=false`.

## Приоритет источников

- окружение важнее значений по умолчанию кода;
- `environment` Compose важнее `env_file`;
- явные параметры шага важнее глобальных defaults;
- после bootstrap база важнее YAML-файла сценариев.
