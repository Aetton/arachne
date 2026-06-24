# Arachne

Оркестратор сборок и деплоя. Тестеры выбирают сценарий, жмут Run — Arachne
дёргает нужную нить (Forgejo workflow, Ansible playbook, OpenTofu), стримит логи
шагами и отдаёт прямую ссылку на артефакт в Nexus. Forgejo при этом невидим.

Парадигма и архитектура — в `MANIFESTO.md` и `ARCHITECTURE.ru.md`.

---

## Быстрый старт (dev, на коленке)

```bash
cp .env.example .env        # минимум: JWT_SECRET, ADMIN_PASSWORD
docker compose up -d        # SQLite, один контейнер, порт 8080
```

Открыть http://localhost:8080, войти как `admin` / значение `ADMIN_PASSWORD`.

Нет ansible / нет доступа к Forgejo на дев-машине? Пауки падают в демо-режим
(ansible-local крутит демо-плейбук, остальные синтезируют результат), так что
морда работает end-to-end из коробки — можно щупать UI без боевой обвязки.

---

## Переменные окружения (`.env`)

Всё читается docker compose автоматически. Что обязательно, что опционально:

### Обязательное в проде

| Переменная | Что это | Пример |
|---|---|---|
| `JWT_SECRET` | Чем подписываются сессии. **Сменить на длинную случайную строку.** Утечёт — подделают вход. | `openssl rand -hex 32` |
| `ADMIN_PASSWORD` | Пароль сидируемого `admin` при первом старте. Сменить сразу после входа. | `S0me-Strong-Pass` |

### Nexus (артефакты)

| Переменная | Что это | Кто потребляет |
|---|---|---|
| `NEXUS_URL` | База Nexus, из неё строятся ссылки на скачивание. | Arachne (ссылки) + пауки (загрузка) |
| `NEXUS_USER` / `NEXUS_PASSWORD` | Креды на upload. В проде — тянуть из OpenBao, не хардкодить. | playbooks / workflow'ы |

### Forgejo (build-нити) + callback

| Переменная | Что это |
|---|---|
| `FORGEJO_URL` | База Forgejo, куда паук шлёт dispatch. |
| `FORGEJO_TOKEN` | PAT с правом дёргать workflow dispatch и отменять раны. |
| `FORGEJO_OWNER` | Владелец реп со сборочными workflow'ами (напр. `redsoft`). |
| `ARACHNE_URL` | **Внешний** URL самой Arachne — его паук кладёт в inputs, по нему раннер стучит обратно. Раннер должен дорезолвить этот адрес. |

### Шина

| Переменная | Значения | Когда менять |
|---|---|---|
| `BUS_BACKEND` | `inmemory` (дефолт) / `nats` | `nats` — когда Arachne в несколько процессов или пауки на других хостах |
| `NATS_URL` | `nats://nats:4222` | только при `BUS_BACKEND=nats` |

### Forgejo-паук, тонкая настройка (опционально)

| Переменная | Дефолт | Что |
|---|---|---|
| `FORGEJO_VERIFY_TLS` | `true` | `false` отключает проверку TLS (самоподписанный CA — лучше добавь CA в доверенные, а не выключай) |
| `FORGEJO_DEADLINE` | `3600` | жёсткий потолок ожидания рана, сек |
| `FORGEJO_SILENCE` | `600` | сколько ждать тишины от раннера до пометки «потерян», сек |

### База

| Переменная | Дефолт | Что |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/portal.db` | на Postgres: `postgresql+psycopg://portal:portal@db/portal` |

---

## Профили docker compose

```bash
docker compose up -d                  # SQLite + inmemory bus (single node)
docker compose --profile pg up -d     # + Postgres
docker compose --profile nats up -d   # + NATS (выстави BUS_BACKEND=nats)
docker compose --profile pg --profile nats up -d   # оба
```

Postgres-переезд: раскомментировать `DATABASE_URL` в `.env`, поднять с
`--profile pg`. Кода не трогать — SQLAlchemy абстрагирует бэкенд. Для миграций
схемы со временем — завести Alembic (`alembic init`, autogenerate, upgrade).

---

## Боевой чеклист

Перед тем как пускать отдел:

1. **`JWT_SECRET`** — длинная случайная строка, не дефолт.
2. **`ADMIN_PASSWORD`** сменён, и после первого входа сменён ещё раз в UI.
3. **`FORGEJO_TOKEN`** — PAT бота, не личный аккаунт. Права: dispatch + cancel.
4. **`ARACHNE_URL`** резолвится и доступен **с раннеров** (они стучат callback'ом).
5. **Реальные workflow'ы** в репах: взять `playbooks/forgejo-workflow.reference.yml`
   за образец, положить в каждую репу как `.forgejo/workflows/build.yml`,
   адаптировать шаги сборки. Плумбинг callback'а (signal/status + токен) оставить.
6. **`WORKFLOW_MAP`** в `api/plugins/spiders/forgejo.py` — выставить под свои
   реальные имена реп и workflow-файлов (сейчас заложены frontend/broker/client-*).
7. **Nexus-креды** — в идеале через OpenBao, не в `.env`.
8. **TLS** — если Forgejo на самоподписанном CA, добавь CA в доверенные внутри
   контейнера (смонтируй и `update-ca-trust`), а не выключай `FORGEJO_VERIFY_TLS`.
9. **Ресурсы ВМ** — портал лёгкий, но под оркестрацию заложи 2-4 vCPU / 4 GB /
   40 GB (сборки идут на раннерах отдельно, не на этой ВМ).

---

## Как раннер общается с Arachne (закон нити)

Build-паук дёргает Forgejo workflow и кладёт в его inputs три значения:
`build_id`, `arachne_callback`, `arachne_token`. Workflow отчитывается обратно:

```
POST {arachne_callback}/signal   {step, status, output}   заголовок X-Arachne-Token
POST {arachne_callback}/status   {status, artifacts}      заголовок X-Arachne-Token
```

Сигнал принимается, только если токен совпал с тем, что Arachne застолбила на
нити при dispatch. Чужой POST без токена — 403. Образец workflow со всей
обвязкой: `playbooks/forgejo-workflow.reference.yml`.

---

## Расширение (без правки ядра)

- **Новый сценарий** → блок в `config/scenarios.yaml` + (если build) workflow в
  репе или (если provision/deploy) playbook. Кода не трогать.
- **Новый паук** (Salt, oVirt, OpenNebula) → класс-наследник `BuildSpider` или
  `ProvisionSpider` в `api/plugins/spiders/`, вызвать `register_spider()`.
  Контракт: `dispatch / stream_logs / get_status / get_artifacts / cancel`.
  Про шину паук **не знает** — её цепляет адаптер.
- **Новый триггер** → класс в `api/plugins/triggers/`, `register_trigger()`.
- **Новая тема** → блок в `frontend/static/css/themes.css` + `<option>` в
  `base.html`.
- **Другая шина** → реализация контракта `core/bus/base.py`, переключение через
  `BUS_BACKEND`.
- **LDAP** → колонка `auth_source` уже уживается с локальными юзерами; добавить
  LDAP-проверку в `auth/` и ставить `auth_source="ldap"`.

---

## Структура

```
api/
  main.py            FastAPI, роуты, callback-нити (/api/threads/...)
  run_engine.py      мост HTTP↔оркестратор, живой буфер логов, fire()
  runview.py         структурный лог → дерево шаги→таски для UI
  database.py        модели User/Team/Run (SQLite/Postgres через DATABASE_URL)
  config_loader.py   загрузка scenarios.yaml
  core/
    orchestrator.py  цикл прогона шагов (Arachne)
    spider.py        контракты BaseSpider/BuildSpider/ProvisionSpider
    thread_adapter.py выставляет пауков на шину (единственный, кто знает шину)
    thread_client.py зов нити через шину + подписка на логи
    switchboard.py   коммутатор callback-нитей (закон нити)
    bus/             контракт шины + inmemory + nats
    subjects.py      топология subject'ов
    events.py        события поверх шины
    context.py       резолвер ${step.field}
    wire_codec.py    сериализация типов для шины
  plugins/
    spiders/         forgejo, ansible-local, ansible-ovirt, tofu-proxmox
    triggers/        manual, schedule, chain
frontend/            Jinja-шаблоны + темы (Dracula/Light/Nord)
config/scenarios.yaml сценарии (формы + шаги + триггеры)
playbooks/           ansible-работа + forgejo-workflow.reference.yml
tofu/                OpenTofu provision (Proxmox)
```
