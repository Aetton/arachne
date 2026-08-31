# Ограничения текущей версии

Ниже — ограничения, о которых лучше знать до production-развёртывания.

## Выполнение

- шаги только последовательные, `needs` ни на что не влияет;
- общего retry/continue-from-failed-step для run пока нет;
- live-буферы находятся в памяти и после рестарта не восстанавливаются;
- незавершённые обычные runs после рестарта не подхватываются;
- отмена best-effort и поддержана не всеми пауками;
- история показывает только 15 записей без пагинации.

TTL временных машин является исключением из правила про рестарт: `managed_machines.expires_at` хранится в PostgreSQL, поэтому lifecycle reaper продолжает cleanup после перезапуска Arachne.

## Сценарии и триггеры

- триггеры обновляются только после рестарта;
- defaults формы не применяются к schedule/chain;
- несколько schedule одного slug конфликтуют;
- циклы `chain` и `scenario` не обнаруживаются;
- вложенный сценарий не проверяет свой ACL;
- источник автоматического запуска не сохраняется.

## OpenTofu / Proxmox

- `tofu-proxmox` требует установленный бинарник OpenTofu; production не должен использовать `TOFU_DEV_FALLBACK`;
- OpenTofu state пока хранится локально в persistent volume, общей remote state backend для нескольких responder-ов нет;
- state key строится по имени стенда, поэтому одинаковые имена нельзя бездумно запускать параллельно;
- state directory после destroy автоматически не очищается;
- отдельного TTL/janitor для orphaned state directories пока нет;
- полноценного reconciler, который сверяет все `managed_machines` с Proxmox после длительной аварии, пока нет;
- Golden Image discovery работает для QEMU templates; LXC templates этим механизмом не поддерживаются;
- system disk определяется эвристикой по boot order и disk interfaces, поэтому экзотическую конфигурацию дисков нужно проверить на реальном template;
- disk resize через provider требует интеграционной проверки свойств диска конкретной версии `bpg/proxmox`;
- текущий provider constraint остаётся широким; после боевой проверки желательно зафиксировать протестированную версию и `.terraform.lock.hcl`;
- guest hostname отдельно не меняется, downstream должен использовать IP/VM artifact;
- IP зависит от QEMU Guest Agent; если VM создана, но IP не получен, run может завершиться ошибкой, однако машина всё равно регистрируется для lifecycle cleanup.

Golden Image profiles хранят только mapping на VM ID. Node, datastore, disk interface, CPU/RAM и размер диска читаются live из Proxmox. Возвращать эти значения в `.env` как второй источник истины не следует.

## Managed machines

- PostgreSQL хранит lifecycle и backend metadata, но отдельная пользовательская страница управления всеми машинами пока не завершена;
- credentials storage и выдача временных credentials пока не реализованы как законченный secret backend;
- SPICE/noVNC console пока не является готовой частью пользовательской карточки VM;
- VM ID в Proxmox может переиспользоваться, поэтому он не считается вечным глобальным идентификатором истории;
- `reap_failed` ретраится, но отдельной политики backoff/лимита попыток пока нет;
- cleanup claim имеет lease, но это не заменяет полноценный distributed lifecycle worker для большой multi-responder установки.

## Другие исполнители

- `ansible-ovirt` — заглушка;
- `ansible-local` без playbook может запускать demo fallback;
- готового отдельного spider-worker CLI для NATS нет.

## Доступ и безопасность

- просмотр конкретного run, SSE и cancel не везде проверяют владельца;
- административные routes требуют `admin`, manage-capabilities к ним не подключены;
- cookie не имеет флага `Secure`;
- CSRF-токенов на формах нет;
- callback token можно передать query-параметром;
- UI не создаёт `deny` ACL;
- импортированный team ACL может хранить slug, а редактор отмечает команды по ID;
- LDAP не реализован.

Proxmox token следует держать только в secret/runtime configuration. Golden Images UI не должен показывать или хранить token secret.

## Данные и интерфейс

- файлы package/artifact остаются в Forgejo, Nexus или другом хранилище; Arachne хранит ссылки и metadata;
- VM artifacts являются структурированными объектами и сохраняются целиком в run;
- `${step.field}` использует только первый артефакт шага;
- YAML-якоря теряются после сохранения и экспорта;
- часть подписей рабочего интерфейса остаётся английской;
- старые Forgejo hub actions лежат в репозитории, но основной паук их не использует.
