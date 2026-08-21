# Резервные копии и миграция

## Что сохранять

Минимальный комплект восстановления:

- дамп PostgreSQL;
- `.env` или его значения из secret manager;
- `config/scenarios.yaml`, если он отличается от примера;
- локальные playbook и OpenTofu-модули;
- внутренний CA и настройки reverse proxy;
- версия образа или commit Arachne.

Артефакты Arachne не хранит, поэтому Nexus/Forgejo резервируются отдельно.

## PostgreSQL

Пример дампа:

```bash
docker compose exec -T db \
  pg_dump -U arachne -d arachne -Fc > arachne.dump
```

Проверяйте восстановление на отдельной базе. Файл, который никогда не проходил
restore, называется не backup, а предметом религиозной надежды.

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

Скрипт рассчитан на пустую целевую базу. Не используйте его как механизм слияния
двух живых инсталляций.

## Сценарии отдельно

YAML export удобен для ревью и переноса сценариев, но не заменяет дамп БД: в нём нет
пользователей, истории runs, всех статусов версий и системной структуры ролей.

После импорта проверьте ACL, потому что YAML содержит только опубликованные сценарии
и собранные правила доступа.
