# Развёртывание

Возьмите за основу `.env.example` и `docker-compose.yml.example`. Реальные адреса,
пароли и токены держите вне Git.

## Подготовка

```bash
cp .env.example .env
cp docker-compose.yml.example docker-compose.yml
```

Заполните как минимум `JWT_SECRET`, `ADMIN_PASSWORD`, `POSTGRES_PASSWORD`, параметры
Forgejo и `NEXUS_URL`. Установите `ENV=production`, чтобы небезопасный JWT secret
ломал старт сразу.

## Запуск

```bash
docker compose config
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8080/healthz
```

Контейнер перед Uvicorn выполняет `alembic upgrade head`. Приложение ждёт healthcheck
PostgreSQL через `depends_on`.

## Reverse proxy

Публикуйте наружу только reverse proxy, завершайте на нём TLS и ограничьте доступ к
административным URL. Текущий cookie не выставляет `Secure`, поэтому проверьте
политику прокси и считайте это известным техническим долгом.

Перед тем как открыть пользователям доступ к порталу:

- настройте TLS и не отключайте проверку сертификатов;
- задайте длинное случайное значение для подписи сессий;
- смените первоначальный пароль администратора;
- используйте отдельные сервисные учётные записи для систем выполнения;
- если используется старый callback hub, убедитесь, что runner имеет доступ к `ARACHNE_URL`;
- настройте резервное копирование PostgreSQL.

Также проверьте:

- часовой пояс контейнера, если используются cron-триггеры;
- доступ Arachne к Forgejo API, Nexus и целевым узлам Ansible/OpenTofu;
- наличие настоящих playbook и `tofu`, чтобы dev fallback не выдал фиктивный успех;
- достаточность `FORGEJO_DEADLINE` для самых долгих сборок;
- что ссылка Actions artifact открывается у нужных пользователей.

## Обновление

```bash
git pull --ff-only
docker compose up -d --build
docker compose logs --tail=200 arachne
```

`make update` выполняет примерно тот же цикл, но Makefile предполагает, что рабочий
`docker-compose.yml` уже существует.
