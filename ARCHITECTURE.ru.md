# Архитектура оркестратора — спецификация контрактов

Портал = тонкое ядро-оркестратор. Всё остальное — плагины: драйверы, триггеры,
артефакт-бэкенды. Добавить новый инструмент (Salt, oVirt, OpenNebula) = написать
плагин под контракт. Ядро никогда не импортит конкретный бэкенд напрямую.

---

## 1. Модель плагинов

Единый реестр, плагины саморегистрируются при импорте. Обнаружение по папкам
`api/plugins/<kind>/` — бросил файл, плагин включился.

```
plugins/
  drivers/
    forgejo.py        BuildSpider
    ansible_local.py  BuildSpider
    salt.py           BuildSpider        (будущее)
    tofu_proxmox.py   ProvisionSpider
    ansible_ovirt.py  ProvisionSpider    (будущее)
    opennebula.py     ProvisionSpider    (будущее)
  triggers/
    manual.py
    schedule.py
    chain.py
    webhook.py        (будущее)
  artifacts/
    nexus.py
    forgejo.py
```

Каждый плагин объявляет `KIND` и `NAME` и зовёт `register(...)`.

---

## 2. Контракт драйвера

Два домена, общий предок. Драйвер не хранит состояние рана — он работает с
`RunHandle`, который сам же и выдал.

```python
@dataclass
class RunHandle:
    driver: str                 # "forgejo", "ansible-ovirt"
    external_id: str            # forgejo run_id / ansible pid / salt jid / tofu workspace
    metadata: dict              # что драйверу нужно, чтобы возобновить/опросить

@dataclass
class LogLine:
    text: str
    stream: str = "stdout"      # stdout|stderr|system
    ts: float = 0.0

class RunStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCESS   = "success"
    FAILED    = "failed"
    CANCELLED = "cancelled"

class BaseSpider(ABC):
    KIND: str                   # "build" | "provision"
    NAME: str                   # уникальное, напр. "forgejo"

    def healthcheck(self) -> bool: ...                       # бэкенд жив?
    def dispatch(self, step: StepSpec, ctx: RunContext) -> RunHandle: ...
    async def stream_logs(self, h: RunHandle) -> AsyncIterator[LogLine]: ...
    def get_status(self, h: RunHandle) -> RunStatus: ...
    def get_artifacts(self, h: RunHandle) -> list[Artifact]: ...
    def cancel(self, h: RunHandle) -> bool: ...
```

`BuildSpider(BaseSpider)` — KIND="build". Производит артефакты (tarball, rpm, installer).
`ProvisionSpider(BaseSpider)` — KIND="provision". Производит ВМ/хост; его
артефакты описывают поднятый ресурс (ip, vm-id, ось).

Зачем разделять: build-бэкенд (Forgejo) и provision-бэкенд (oVirt) разделяют
одни и те же хуки жизненного цикла, но под "артефактом" понимают разное.
Разделение держит YAML честным насчёт того, что шаг реально делает.

---

## 3. Абстракция артефактов

Одна форма, любой бэкенд. Оркестратор прокидывает артефакты между шагами, а UI
рендерит скачивание/инспекцию по полю `type`.

```python
@dataclass
class Artifact:
    name: str
    type: str          # "nexus" | "forgejo" | "vm" | "host" | ...
    location: str      # repo/path, run_id, vm-id — зависит от бэкенда
    download_url: str | None   # строится если резолвится; None для нескачиваемых
    metadata: dict             # ip, size, checksum, ...
```

---

## 4. Богатая модель ВМ (решение по п.3)

Раз осей сборки и тестов три (redos7 / redos8 / windows), provision-артефакт
несёт достаточно структуры, чтобы следующий шаг знал куда и как катить.

```python
@dataclass
class VMArtifact(Artifact):
    type: str = "vm"
    # в metadata кладётся структура:
    # {
    #   "os":        "redos8",          # redos7 | redos8 | windows
    #   "arch":      "x86_64",
    #   "hostname":  "test-1.0.5-redos8",
    #   "ip":        "10.81.19.200",
    #   "ssh_port":  22,                 # 5985/winrm для windows
    #   "conn":      "ssh",              # ssh | winrm
    #   "vcpus":     4,
    #   "ram_mb":    8192,
    #   "disk_gb":   40,
    #   "vm_id":     "9001",             # id в бэкенде (proxmox/ovirt)
    #   "backend":   "tofu-proxmox",
    #   "state":     "running",
    # }
```

Следующий шаг достаёт это так:
- `${vm.ip}`        → IP
- `${vm.os}`        → ось (выбрать как катить: rpm vs installer)
- `${vm.conn}`      → ssh или winrm
- `${vm.ssh_port}`  → порт подключения

Так deploy-шаг сам разрулит: на redos катит rpm по ssh, на windows installer по
winrm — потому что вся инфа о цели пришла из provision-артефакта.

---

## 5. Оркестрация шагов

Сценарий = список шагов. Оркестратор гоняет по порядку, копит выходы каждого
шага в `RunContext`, резолвит `${...}` перед запуском следующего.

```yaml
create-stage:
  label: "Создать тестовый стенд"
  params:
    - {name: version, type: string, required: true}
    - {name: release, type: choice, options: [prod, staging, dev]}
    - {name: os,      type: choice, options: [redos7, redos8, windows]}
    - {name: debug,   type: boolean, default: false}
  steps:
    - id: build-fe
      driver: forgejo
      action: build
      with: {component: frontend, version: "${params.version}", debug: "${params.debug}"}

    - id: build-br
      driver: forgejo
      action: build
      with: {component: broker, version: "${params.version}", debug: "${params.debug}"}

    - id: vm
      driver: tofu-proxmox          # замена на ansible-ovirt = одна строка
      action: provision
      with:
        name: "test-${params.version}-${params.os}"
        os: "${params.os}"

    - id: deploy
      driver: ansible-local
      action: deploy
      with:
        target:   "${vm.ip}"          # выход шага 'vm'
        conn:     "${vm.conn}"        # ssh | winrm
        os:       "${vm.os}"
        frontend: "${build-fe.artifact}"
        broker:   "${build-br.artifact}"
```

Ссылки в контексте:
- `${params.X}`          — вход сценария
- `${<step_id>.<field>}` — именованное поле из метадаты артефакта прошлого шага
- `${<step_id>.artifact}` — основной артефакт прошлого шага (передаётся целиком)

Шаги по умолчанию последовательны. `needs: [id1, id2]` для DAG — на будущее,
сейчас не блокирует.

---

## 6. Движок триггеров

Триггеры — плагины, которые *запускают ран сценария*. Ядро отдаёт точку входа
`fire(scenario_key, params, source)`; каждый триггер её зовёт.

```python
class BaseTrigger(ABC):
    NAME: str                       # "manual" | "schedule" | "chain"
    def setup(self, scenario_key: str, cfg: dict) -> None: ...
    # триггер зовёт orchestrator.fire(...) когда условие выполнено
```

Объявление в сценарии:

```yaml
create-stage:
  triggers:
    - {type: manual}                              # кнопка (по умолчанию)
    - {type: schedule, cron: "0 2 * * *"}         # ночная сборка
    - {type: chain, after: build-nightly, on: success}  # после другого сценария
    # - {type: webhook, secret_env: WH_SECRET}    # будущий плагин
  steps: [...]
```

- `manual`   — рендерит форму + кнопку Run.
- `schedule` — задача APScheduler; стреляет с дефолтными параметрами.
- `chain`    — подписка на событие завершения рана; стреляет когда названный
               сценарий закончился с нужным статусом. **Гранулярность:
               per-scenario** (ран B после сценария A). Per-step — отдельным
               плагином, если понадобится.
- `webhook`  — будущее. Роут + проверка подписи, зовёт `fire(...)`.

Движок триггеров сидит на крошечной внутренней шине событий (`run.completed`,
`run.failed`), чтобы `chain` и будущие плагины подписывались без ведома ядра.

---

## 7. Что реально внутри ядра

- загрузчик сценариев (YAML → список StepSpec + конфиг триггеров)
- `RunContext` + резолвер `${...}`
- цикл оркестрации (dispatch → stream → собрать артефакты → следующий)
- реестры драйверов/триггеров/артефактов
- шина событий
- персист ранов (БД) + живой буфер логов (уже готово)

Всё остальное — плагины. Forgejo build-путь, Ansible deploy-путь,
Proxmox/oVirt provision-пути — все сменные без касания ядра.

---

## Зафиксированные решения

1. Синтаксис ссылок: **`${step.field}`** — по красоте, без Jinja-лапши.
2. `chain`: **per-scenario** сейчас; per-step — плагином при необходимости.
3. Provision-артефакт: **богатый `type: vm`** с осью/IP/conn/ресурсами в
   метадате — потому что осей три (redos7/redos8/windows) и deploy-шаг должен
   сам разруливать способ доставки.

---

## Статус реализации

Ядро и контракты — **написаны и проверены вживую**:

- `core/types.py` — RunHandle, Artifact, StepSpec, RunStatus, LogLine ✓
- `core/spider.py` — BaseSpider + BuildSpider/ProvisionSpider ✓
- `core/context.py` — RunContext + резолвер `${...}` (тесты зелёные:
  булевы сохраняются, артефакт прокидывается объектом, интерполяция строк) ✓
- `core/orchestrator.py` — цикл прогона шагов ✓
- `core/events.py` — шина событий ✓
- `core/trigger.py` — контракт триггера ✓
- `core/registry.py` — автозагрузка плагинов из `plugins/*` ✓

Плагины-драйверы:
- `forgejo` (BuildSpider, dispatch API + поллинг) ✓
- `ansible-local` (BuildSpider, со стримингом и демо-фолбэком) ✓
- `tofu-proxmox` (ProvisionSpider, богатый VM-артефакт) ✓
- `ansible-ovirt` (ProvisionSpider, стаб-шаблон для твоего будущего кейса) ✓

Плагины-триггеры:
- `manual`, `chain` (через шину), `schedule` (APScheduler/cron) ✓

**Проверено end-to-end:** многошаговый `create-stage` (build → provision →
deploy) через три разных драйвера, артефакты текут между шагами, `${vm.ip}` и
`${vm.os}` резолвятся. Chain-триггер стреляет на success, молчит на failed.

**Осталось (следующий заход):** переключить `main.py` со старого `run_engine`
на новый `orchestrator`, перевести YAML-сценарии на step-формат, подключить
запуск APScheduler в lifespan, прорисовать в UI multi-step раны (сейчас UI
рендерит одношаговые).

---

## Шина — нервная система паутины

Транспортный слой под всеми контрактами. Паук дотягивается до любой нити через
шину, не зная, где нить висит — в том же процессе или на другом конце NATS.

**Принцип:** шина спрятана в ядре. Контракты плагинов (драйверы, триггеры) про
неё **не знают**. Добавить нить = реализовать контракт драйвера, и только.
Подмена шины и добавление нити — независимые оси. Новый плагин не обрастает
обрядом «подпишись/опубликуй».

Контракт (`core/bus/base.py`):
- `publish / subscribe` — события (run.completed, chain-триггеры)
- `request / reply`     — вызов нити (драйвера), где бы та ни жила

Реализации:
- `InMemoryBus` (дефолт) — pub/sub + req/reply в процессе, ноль внешних
  сервисов. Wildcards `*` и `>` как в NATS, чтобы поведение совпадало.
- `NatsBus` — `BUS_BACKEND=nats` + `NATS_URL`. Те же четыре примитива поверх
  NATS subjects. Драйверы-нити могут жить отдельными процессами: каждый зовёт
  `bus.reply(subject, handler)`, паук — `bus.request(subject, ...)`, NATS
  маршрутизирует. Код ядра идентичен — меняется только бэкенд.

Subjects лягут на паучью топологию: `arachne.event.run.completed`,
`arachne.thread.build.forgejo`, `arachne.thread.provision.ovirt`.

`events.py` стал тонким фасадом над шиной — публичный API `emit`/`subscribe`
не изменился, так что оркестратор и chain-триггер ничего не заметили.

**Проверено:** pub/sub, request/reply, wildcards, no_responder; полный ран и
multi-step через шину; chain-триггер через шину стреляет на success, молчит на
failed. Бэкенд `inmemory` по умолчанию. Переключение на NATS — одна env-переменная.

### Вызов нитей через шину (multi-process готовность)

Оркестратор больше **не зовёт драйверы напрямую**. Он зовёт нить через шину:

```
orchestrator → thread_client.run_step(run_id, driver, step)
            → bus.request("arachne.thread.{driver}.run", ...)
            → thread_adapter._run_responder  (где бы он ни жил)
                 ├ driver.dispatch()
                 ├ driver.stream_logs()  → publish "arachne.thread.log.{run_id}"
                 ├ driver.get_status()
                 └ driver.get_artifacts()
            ← {status, handle, artifacts}
```

Логи текут отдельным потоком (`publish`/`subscribe` на `arachne.thread.log.{run_id}`),
команда — одним `request`. Это switchboard-модель, обобщённая с «Forgejo
callback» до «любая нить».

**Контракт драйвера не изменился ни на байт.** Шину знает только
`thread_adapter`. Драйвер пишет `dispatch/stream_logs/get_status/get_artifacts`
— и всё. Выставление на шину делает адаптер (`expose_all()` в одном процессе;
в multi-process каждый драйвер-хост зовёт `expose()` для своей нити).

**Multi-process:**
- single (дефолт): `expose_all()` при старте, in-memory bus замыкает request на
  тот же процесс — поведение идентично прямому вызову.
- distributed: `BUS_BACKEND=nats`; драйвер-хост поднимается, зовёт `expose()`
  для своей нити, паук достаёт его через `bus.request`. Если хост не поднят —
  `no_responder`, ран честно падает (не висит).

**Проверено:** dispatch+stream+artifacts через шину (одношаговый и multi-step с
прокидыванием артефактов между шагами); сериализация Artifact↔dict через шину;
graceful `no_responder` когда нить не выставлена.


---

## Ревью-правки (паучий рефактор)

Драйверы переименованы в **пауков** (spiders): Arachne — королева в центре,
пауки — её выводок, бегают по нитям к чужим опорам и тащат добычу. Рефактор
глубокий — никакой размазанной штукатурки под лицом.

- `BaseSpider` / `BuildSpider` / `ProvisionSpider`, папка `plugins/spiders/`,
  `register_spider` / `get_spider`, `RunHandle.spider`, `StepSpec.spider`.

Пять пунктов ревью закрыты:

1. **thread_adapter ≠ оркестратор.** Адаптер исполняет ровно один step через
   одного паука (dispatch→stream→status→artifacts). Не знает сценариев, needs,
   params, DAG. Arachne владеет сценарием, адаптер — исполнением шага.

2. **Логи с sequence number.** Каждая строка несёт
   `{run_id, step_id, seq, stream, text, ts}`. Под NATS строки не перепутаются.

3. **Структурный error в финале.** Не только status, но и
   `error{type, message, details}` — failed больше не унылый кирпич
   (DispatchError / BackendError / Cancelled / TransportError).

4. **Subject'ы скучные и стабильные.** `arachne.thread.{kind}.{spider}.run`,
   `.cancel`, `.health`, `arachne.thread.log.{run_id}.{step_id}`,
   `arachne.event.run.*`. `kind` (build/provision) в пути — можно подписаться
   на класс нитей: `arachne.thread.build.>`.

5. **Cancel рядом.** Отдельный subject `arachne.thread.{kind}.{spider}.cancel`.
   Адаптер держит мапу `run_id:step_id → asyncio.Task`. Cancel прерывает
   задачу, паук **сам режет свою нить** через `cancel(handle)` (Forgejo —
   отмена run через API; Ansible — SIGTERM процессу). Мапа чистится.

**Проверено:** загрузка пауков с KIND; одношаговый и multi-step (build+provision
вперемешку) через шину; seq монотонный и step_id-тегированный; структурный
error при провале; cancel через subject прерывает работу, зовёт паучий
cancel(), чистит мапу.
