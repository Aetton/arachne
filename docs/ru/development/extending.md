# Расширение Arachne

## Новый паук

Унаследуйте `BuildSpider` или `ProvisionSpider`, задайте уникальный `NAME` и
реализуйте:

- `dispatch(step, ctx) -> RunHandle`;
- `stream_logs(handle)` как async iterator;
- `get_status(handle)`;
- при необходимости `get_artifacts`, `cancel`, `healthcheck`.

Зарегистрируйте экземпляр через `register_spider`. Автозагрузчик импортирует модули
из `plugins.spiders`.

Паук не должен импортировать шину и управлять сценарием. Его мир — один шаг и один
внешний исполнитель. Thread adapter сам выставит responder и упакует ошибки.

Для внешнего процесса через NATS нужно поднять bus, зарегистрировать паука и вызвать
`expose(spider)`. Готового CLI worker пока нет.

## Новый триггер

Унаследуйте `BaseTrigger`, задайте `NAME`, реализуйте `setup(scenario_key, cfg)` и
зарегистрируйте класс через `@register_trigger`. Для запуска вызывайте переданный
`self.fire(scenario_key, params, source=...)`.

Триггер не должен напрямую создавать строки `Run`: единая точка входа отвечает за
снимок сценария, live-state и сохранение результата.

## Новый backend шины

Реализуйте контракт `Bus`: publish/subscribe/unsubscribe/request/reply и при
необходимости start/stop. Затем добавьте выбор backend в factory.

Поведение timeout и no-responder должно возвращать ошибку в словаре, чтобы thread
client превратил её в `TransportError`.

## Новый тип параметра

Это изменение затрагивает как минимум:

- шаблон `frontend/templates/scenario_form.html`;
- сбор формы в `api/main.py`;
- валидацию и подсказки `admin/scenario_form.html`;
- metadata редактора;
- документацию DSL.

Динамические источники живут в `api/input_sources.py`. Функция enrichment обязана
работать с копией definition, чтобы открытие формы не мутировало опубликованную версию.

## Контракт артефакта

Возвращайте `Artifact(name, type, location, download_url, metadata)`. Кладите в
metadata стабильные скалярные поля, которые пригодятся следующему шагу. Первый
артефакт становится основным для `${step.field}`.

Не помещайте секреты в metadata: артефакты сохраняются в run и могут попасть в UI.
