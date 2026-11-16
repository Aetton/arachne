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

Инструменты документации изолированы в каталоге `docs-site`:

```bash
cd docs-site
npm ci
npm run dev
```

Для контейнера задайте `DOCS_BASE_PATH=/wiki`, для GitHub Pages —
`DOCS_BASE_PATH=/arachne`. Затем выполните `npm run build` и `npm run check:export`
с тем же значением переменной. Без префикса сборка предназначена для корня сайта.

## Проверки перед коммитом

```bash
cd docs-site
npm ci
npm run build
npm run check:export
```

Основные проверки приложения: `python scripts/check.py` из корня репозитория
после установки `requirements-dev.txt` и `npm ci`. Тесты внешних backend используют
подмены и не подтверждают реальное выполнение инфраструктурных операций.

## Структура

| Каталог | Содержимое |
|---|---|
| `api/` | FastAPI, БД, ядро, пауки и триггеры |
| `frontend/` | Jinja2, CSS и JavaScript |
| `docs/` | Markdown-контент документации |
| `docs-site/` | Fumadocs, сборка статического справочника |
| `config/` | seed сценариев и справка |
| `playbooks/` | Ansible и исторические workflow examples |
| `tofu/` | пример модуля OpenTofu |
| `actions/`, `hubs/` | legacy callback actions для Forgejo |
| `migrations/` | Alembic |
| `scripts/` | bootstrap и перенос SQLite |
