# Диагностика неполадок

## Логи приложения

```bash
docker compose logs -f --tail=200 arachne
```

## Состояние контейнеров

```bash
docker compose config
docker compose ps
```

## Портал не стартует

- при `ENV=production` проверьте `JWT_SECRET`;
- проверьте `DATABASE_URL` и healthcheck PostgreSQL;
- посмотрите вывод Alembic до запуска Uvicorn;
- убедитесь, что `docker-compose.yml` создан из example;
- проверьте права чтения смонтированных config/playbooks/certs.

## Сценарий не виден

Проверьте опубликованную версию, `enabled`, `scenarios.view` и ACL `view`. Компонент команды сам по себе доступ не выдаёт.

## Ветки не загрузились

Ошибка показывается прямо под полем. Проверьте `FORGEJO_URL`, токен, TLS, owner/repo и наличие Forgejo-шага, указанного в `source.step`. Результат кэшируется, поэтому после исправления подождите `INPUT_SOURCE_CACHE_TTL` или перезапустите приложение.

## Forgejo dispatch упал до запуска

Preflight проверяет workflow на выбранном ref. Частые причины:

- файл лежит не в `.forgejo/workflows/`;
- в feature-ветке файла ещё нет;
- токен не читает contents;
- `workflow` указан с опечаткой;
- внутренний CA не доверен контейнеру.

## Golden Images не показывает templates

Проверьте сначала не OpenTofu, а прямой доступ Arachne к Proxmox API.

В `.env` должны быть только connection/auth параметры:

```dotenv
PROXMOX_VE_ENDPOINT=https://pve.example.internal:8006/
PROXMOX_VE_API_TOKEN=arachne@pve!arachne=<TOKEN_SECRET>
PROXMOX_VE_INSECURE=false
```

Проверка с хоста:

```bash
set -a
. ./.env
set +a

curl --fail --show-error \
  --cacert ./certs/ca.crt \
  -H "Authorization: PVEAPIToken=$PROXMOX_VE_API_TOKEN" \
  "${PROXMOX_VE_ENDPOINT%/}/api2/json/cluster/resources?type=vm"
```

Если здесь ошибка, Golden Images UI тоже не сможет сделать discovery.

Типовые причины:

- неверный endpoint;
- token secret записан не целиком;
- token не имеет `VM.Audit`/не видит нужные VM;
- корпоративный CA не подключён;
- `PROXMOX_VE_INSECURE=false`, но сертификат не доверен;
- сетевой ACL не пропускает HTTPS к `:8006`.

## Golden Image помечен broken

Профиль остаётся в PostgreSQL, но выбранный template не прошёл live discovery.

Проверьте:

1. существует ли VM ID;
2. является ли объект template;
3. видит ли его сервисный token;
4. доступен ли node;
5. читается ли `/nodes/<node>/qemu/<vmid>/config`;
6. не был ли template пересоздан с новым VM ID.

Не чините broken profile добавлением `TOFU_TEMPLATE_*` в `.env`. Исправьте mapping в **Control -> Golden Images** или доступ к Proxmox.

## Provision говорит, что профиль не настроен

Если сценарий содержит:

```yaml
os: redos8
```

и `image` не указан, Arachne ищет Golden Image profile с ключом `redos8`.

Проверьте:

- профиль существует;
- профиль enabled;
- profile key совпадает с `os`;
- если используется `image`, его значение совпадает с profile key;
- карточка профиля имеет состояние ready.

## Disk override отклонён

Spider сравнивает `resources.disk_gb` с фактическим system disk выбранного template.

Например:

```yaml
resources:
  disk_gb: 20
```

будет отклонён, если template имеет 40 GiB.

Если spider не может определить system disk, проверьте boot order и конфигурацию дисков template. Экзотические схемы с несколькими bootable дисками нужно валидировать отдельно.

## OpenTofu получил 403

Сначала смотрите точную privilege в ответе Proxmox. Для clone lifecycle обычно нужны права на allocate/audit/clone/power, а для overrides дополнительно:

```text
VM.Config.CPU
VM.Config.Memory
VM.Config.Disk
```

Не выдавайте `Administrator` только ради того, чтобы ошибка исчезла. Добавляйте минимальную реально требуемую privilege.

## VM создалась, но IP нет

Для `tofu-proxmox` IP читается через QEMU Guest Agent.

Проверьте в golden image:

```bash
systemctl status qemu-guest-agent
```

а в Proxmox убедитесь, что guest agent включён для VM/template.

Важно: если VM уже получила `vm_id`, Arachne регистрирует её как managed machine даже при отсутствии IP. Это позволяет TTL/manual cleanup не потерять реально существующую машину.

## TTL не удалил машину ровно в секунду

Reaper работает раз в минуту. `expires_at` — абсолютный timestamp, а cleanup запускается на ближайшем следующем проходе scheduler-а.

Проверьте:

```sql
SELECT id,name,state,expires_at,destroy_claimed_at,destroyed_at
FROM managed_machines
ORDER BY id DESC;
```

Ожидаемые переходы:

```text
running -> destroying -> destroyed
```

При ошибке:

```text
reap_failed
```

такой cleanup будет подобран повторно.

## Машина зависла в destroying после падения Arachne

Cleanup claim имеет lease. После его истечения reaper имеет право подобрать запись повторно. Не сбрасывайте состояние сразу руками: сначала убедитесь, что предыдущий `tofu destroy` действительно не продолжает работу во внешнем backend.

## После смены Golden Image старый stand не удаляется

Смена mapping сама по себе не должна ломать destroy. Backend metadata конкретной созданной VM сохраняются в `managed_machines`.

Если destroy всё же не работает, проверьте:

- существует ли `TOFU_STATE_ROOT/<stand-name>/terraform.tfstate`;
- не был ли state volume потерян;
- не изменилось ли имя stand;
- не удалена ли VM вручную в Proxmox;
- что записано в `backend_metadata` managed machine.

## Run запущен, но логов нет

Проверьте endpoints run и logs вашей версии Forgejo. `404`/`409` на раннем этапе нормальны, постоянная ошибка status API — нет. Увеличение poll interval уменьшит нагрузку, но не починит отсутствующий endpoint.

## Артефакт не найден

- Actions artifact должен быть непросроченным;
- Nexus URL должен присутствовать в полном логе;
- для короткой формы используйте ровно `uploaded to repo/path`;
- Arachne строит ссылку от `NEXUS_URL` и не проверяет содержимое файла.

## Ansible или OpenTofu подозрительно быстро «успешны»

Проверьте, не включён ли dev fallback. В production `TOFU_DEV_FALLBACK` должен быть `false`, а внутри контейнера должен существовать настоящий бинарник `tofu`.

```bash
docker compose exec arachne tofu version
```

## Run завис в running после рестарта

Live-состояние обычного run хранится в памяти и после рестарта не восстанавливается. Reconciler для незавершённых runs пока отсутствует.

Это не относится к TTL managed machines: их `expires_at` хранится в PostgreSQL и продолжает обслуживаться lifecycle reaper после старта приложения.
