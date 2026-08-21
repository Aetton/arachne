# Локальная разработка

```bash
cp .env.example .env
cp docker-compose.yml.example docker-compose.yml
docker compose up -d --build
docker compose logs -f arachne
```

Для запуска API без контейнера нужны Python 3.12, зависимости из
`api/requirements.txt` и доступная база. Из каталога `api`:

```bash
export DATABASE_URL=sqlite:///./data/arachne.db
uvicorn main:app --reload
```

SQLite удобен для короткой разработки, production default — PostgreSQL.

Инструменты документации изолированы в каталоге `docs`:

```bash
cd docs
npm ci
npm run docs:dev
```

Production-сборка документации запускается командой `npm run docs:build`.

## Проверки перед коммитом

```bash
cd docs
npm ci
npm run docs:build
```

В репозитории сейчас нет полноценного набора автотестов. Поэтому дополнительно
проверьте старт приложения, вход, открытие сценария, ручной run и конкретный backend,
которого касается изменение.

## Структура

| Каталог | Содержимое |
|---|---|
| `api/` | FastAPI, БД, ядро, пауки и триггеры |
| `frontend/` | Jinja2, CSS и JavaScript |
| `docs/` | VitePress |
| `config/` | seed сценариев и справка |
| `playbooks/` | Ansible и исторические workflow examples |
| `tofu/` | пример модуля OpenTofu |
| `actions/`, `hubs/` | legacy callback actions для Forgejo |
| `migrations/` | Alembic |
| `scripts/` | bootstrap и перенос SQLite |
