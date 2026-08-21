# Forgejo Actions

Текущая интеграция рассчитана на API Forgejo v16. Arachne сама запускает workflow,
читает его состояние и логи, получает Actions artifacts и умеет отменять run.
Callback-обвязка workflow больше не нужна.

## Что нужно от Forgejo

- workflow лежит в `.forgejo/workflows/` на ref, который запускает Arachne;
- у workflow есть `workflow_dispatch`;
- каждый input, переданный сценарием, объявлен в workflow;
- токен Arachne имеет доступ к репозиторию, Actions runs, логам и артефактам;
- Arachne доверяет TLS-сертификату Forgejo.

## Минимальный workflow

```yaml
name: Build backend

on:
  workflow_dispatch:
    inputs:
      version:
        type: string
        required: true
      debug:
        type: boolean
        required: false
        default: false

jobs:
  build:
    runs-on: linux
    steps:
      - uses: actions/checkout@v4

      - name: Build
        shell: bash
        run: ./build.sh "${{ inputs.version }}"

      - name: Upload Actions artifact
        uses: actions/upload-artifact@v4
        with:
          name: backend-${{ inputs.version }}
          path: dist/
```

Соответствующий шаг Arachne:

```yaml
- id: build
  spider: forgejo
  action: build
  with:
    owner: platform
    repo: backend
    workflow: build.yml
    branch: "${params.branch}"
    version: "${params.version}"
    debug: "${params.debug}"
```

`owner`, `repo`, `workflow`, `ref`, `branch` и `component` — управление пауком.
Остальные поля превращаются в workflow inputs.

## Как Arachne находит run

Dispatch отправляется с расширением Forgejo:

```json
{
  "ref": "main",
  "inputs": {"version": "1.2.3"},
  "return_run_info": true
}
```

Если ответ содержит `id` или `run_id`, паук связывает его сразу. Если сервер ответил
без метаданных, Arachne до десяти раз ищет свежий run этого workflow с событием
`workflow_dispatch` и нужной веткой.

До dispatch выполняется preflight: Arachne читает файл workflow через contents API
на выбранном ref. Поэтому ошибка «workflow существует только в main, а запускается
feature-ветка» находится до старта, а не после танца с пустым списком runs.

## Логи

Раз в `FORGEJO_POLL_INTERVAL` секунд Arachne читает общий архив логов и статус run.
Forgejo v16 отдаёт ZIP, где каждый job — отдельный `.log`. Arachne декодирует UTF-8,
убирает ANSI/control-мусор и создаёт раскрывающуюся группу:

```text
::group::Forgejo job: build.log
...
::endgroup::
```

Повторно полученная часть лога не публикуется. Если Forgejo пересобрал архив так, что
обычный prefix уже не совпадает, Arachne сравнивает строки с начала и отправляет хвост.

`404` и `409` при раннем запросе логов считаются временным отсутствием лога. Ошибка
опроса самого run завершает шаг как `failed`.

## Артефакты

После терминального статуса паук получает Actions artifacts. Для каждого
непросроченного элемента сохраняются имя, ID, размер, archive URL и ссылка на страницу
загрузки Forgejo.

Дополнительно полный лог сканируется на:

```text
https://nexus.example.internal/repository/dev-artifacts/path/file.rpm
uploaded to dev-artifacts/path/file.rpm
```

Во втором случае URL строится от `NEXUS_URL`. Ссылки очищаются от типичных закрывающих
кавычек и знаков препинания, одинаковые ссылки удаляются.

Чтобы Nexus-артефакт находился надёжно, печатайте полную ссылку отдельной строкой.

## Статусы

| Forgejo | Arachne |
|---|---|
| `success`, `skipped`, `neutral` | `success` |
| `cancelled`, `canceled` | `cancelled` |
| `failure`, `failed`, `timed_out`, `action_required`, `stale`, `startup_failure` | `failed` |
| `pending`, `queued`, `waiting`, `requested` | `pending` |
| остальное незавершённое | `running` |

Завершённый run без понятного conclusion считается упавшим.

## Отмена и timeout

Отмена вызывает `POST .../actions/runs/{id}/cancel`. Ответ `409` означает, что run
уже мог закончиться; Arachne перечитывает состояние и считает отмену успешной только
для терминального статуса.

`FORGEJO_DEADLINE` ограничивает ожидание всего run. По умолчанию это 3600 секунд.
Общий запрос к нити дополнительно ограничен двумя часами.

## Старый callback/hub-контракт

В репозитории ещё есть:

- `actions/forgejo/init-bash` и `init-pwsh`;
- копии в `hubs/forgejo`;
- `/api/threads/{build_id}/signal` и `/status`;
- reference workflow с `build_id`, `arachne_callback`, `arachne_token`.

Это слой совместимости со старым Forgejo-пауком, который ждал сигналы от runner.
Текущий паук не создаёт switchboard-thread, не добавляет эти три inputs и не ждёт
callback. Не добавляйте их в новые workflow ради Arachne.

Сами init-actions при пустых callback/token работают как noop. Их можно использовать
отдельно как экспериментальную обвязку логов, но основной портал от присланных ими
сигналов не свяжет данные с современным Forgejo run.
