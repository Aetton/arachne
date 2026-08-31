# Резервные копии и миграция

## Что сохранять

Минимальный комплект восстановления:

- дамп PostgreSQL;
- `.env` или его значения из secret manager;
- persistent OpenTofu state из `TOFU_STATE_ROOT`;
- `config/scenarios.yaml`, если он отличается от примера;
- локальные playbook и OpenTofu-модули;
- внутренний CA и настройки reverse proxy;
- версия образа или commit Arachne.

Артефакты пакетов Arachne не хранит, поэтому Nexus/Forgejo резервируются отдельно.

Для инфраструктурного provisioning одного PostgreSQL недостаточно: lifecycle машины хранится в БД, а terraform/OpenTofu state — в отдельном persistent volume.

## Что теперь хранит PostgreSQL

Кроме пользователей и сценариев, база содержит:

- Golden Image profiles;
- mapping `profile -> Proxmox template VM ID`;
- structured run artifacts;
- `managed_machines`;
- `expires_at`, `destroy_claimed_at`, `destroyed_at`;
- backend metadata конкретных созданных VM.

Поэтому потеря PostgreSQL означает потерю не только истории, но и части управляемого lifecycle.

Фактическая конфигурация template при этом не копируется в БД: node, storage, CPU, RAM и disks остаются в Proxmox и после восстановления читаются заново через API.

## PostgreSQL

Пример дампа:

```bash
docker compose exec -T db \
  pg_dump -U arachne -d arachne -Fc > arachne.dump
```

Проверяйте восстановление на отдельной базе. Файл, который никогда не проходил restore, называется не backup, а предметом религиозной надежды.

После restore проверьте:

```sql
SELECT count(*) FROM runs;
SELECT count(*) FROM managed_machines;
SELECT count(*) FROM golden_image_profiles;
```

Имена таблиц должны соответствовать фактической схеме установленной версии.

## OpenTofu state

В Compose state находится в persistent volume, смонтированном в `TOFU_STATE_ROOT`.

Для каждой машины используется отдельный каталог по имени stand. Там хранится `terraform.tfstate` и рабочие данные module.

Перед миграцией сохраните весь volume целиком.

Если восстановить PostgreSQL без OpenTofu state, Arachne будет помнить, что managed machine существовала, но штатный `tofu destroy` может не иметь состояния, необходимого для удаления ресурса.

Если восстановить state без PostgreSQL, OpenTofu может технически знать ресурсы, но Arachne потеряет ownership, TTL и связь с run/user.

Полный комплект выглядит так:

```text
PostgreSQL
+ OpenTofu state volume
+ runtime secrets
+ CA
+ версия Arachne
```

## Golden Images после миграции

Golden Image profiles сохраняются в PostgreSQL, но после переноса Arachne должна заново проверить их против Proxmox.

После старта:

1. откройте **Control -> Golden Images**;
2. убедитесь, что profiles не broken;
3. проверьте VM ID и live metadata;
4. если Proxmox cluster другой, переназначьте profiles на templates нового окружения.

Не переносите node/storage metadata вручную. Их Arachne получает из целевого Proxmox API.

## Managed machines после миграции

Если переносятся и Arachne, и тот же Proxmox backend, проверьте активные записи:

```sql
SELECT id,name,vm_id,state,expires_at
FROM managed_machines
WHERE state <> 'destroyed'
ORDER BY id;
```

Сверьте их с реальными VM в Proxmox.

Особенно проверьте записи `destroying` и `reap_failed`: после запуска scheduler может продолжить lifecycle cleanup.

Если миграция идёт в другой Proxmox cluster, активные managed machines нельзя считать автоматически переносимыми только из-за наличия строк в БД.

## SQLite → PostgreSQL

SQLite поддерживается как старый источник и режим разработки. Для переноса:

1. остановите Arachne;
2. сделайте копию SQLite-файла;
3. поднимите пустой PostgreSQL;
4. запустите мигратор;
5. поднимите приложение и проверьте количество сущностей.

```bash
docker compose up -d db
python scripts/migrate_sqlite_to_postgres.py \
  --sqlite ./data/arachne.db \
  --postgres postgresql+psycopg://arachne:password@localhost/arachne
docker compose up -d
```

Скрипт рассчитан на пустую целевую базу. Не используйте его как механизм слияния двух живых инсталляций.

Если целевая версия схемы содержит новые таблицы managed lifecycle, отдельно проверьте, что мигратор действительно переносит нужные модели. Если нет, сначала обновите/мигрируйте Arachne штатным путём, а уже потом переносите данные.

## Сценарии отдельно

YAML export удобен для ревью и переноса сценариев, но не заменяет дамп БД: в нём нет пользователей, истории runs, всех статусов версий, системной структуры ролей, Golden Image profiles и managed machines.

После импорта проверьте ACL, потому что YAML содержит только опубликованные сценарии и собранные правила доступа.
