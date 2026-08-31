# Развёртывание

Возьмите за основу `.env.example` и `docker-compose.yml.example`. Реальные адреса,
пароли и токены держите вне Git.

## Подготовка

```bash
cp .env.example .env
cp docker-compose.yml.example docker-compose.yml
```

Заполните как минимум `JWT_SECRET`, `ADMIN_PASSWORD`, `POSTGRES_PASSWORD`, параметры Forgejo и `NEXUS_URL`. Установите `ENV=production`, чтобы небезопасный JWT secret ломал старт сразу.

Если планируется Proxmox/OpenTofu provisioning, добавьте только connection/auth параметры:

```dotenv
PROXMOX_VE_ENDPOINT=https://pve.example.internal:8006/
PROXMOX_VE_API_TOKEN=arachne@pve!arachne=<TOKEN_SECRET>
PROXMOX_VE_INSECURE=false
```

Golden Image mappings после старта настраиваются через **Control -> Golden Images**. VM ID шаблонов, node, datastore и disk metadata в `.env` не копируются.

## Запуск

```bash
docker compose config
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8080/healthz
```

Контейнер перед Uvicorn выполняет `alembic upgrade head`. Приложение ждёт healthcheck PostgreSQL через `depends_on`.

Проверьте OpenTofu:

```bash
docker compose exec arachne tofu version
```

Если команда отсутствует, production provisioning нельзя считать готовым.

## PostgreSQL как lifecycle state

Кроме пользователей, сценариев и runs, PostgreSQL хранит управляемые сущности инфраструктуры:

- Golden Image profiles;
- `managed_machines`;
- абсолютный `expires_at` для TTL;
- backend metadata, нужные для последующего destroy.

Поэтому резервное копирование PostgreSQL является частью восстановления lifecycle, а не только пользовательских настроек.

OpenTofu state хранится отдельно в `TOFU_STATE_ROOT`, который в Compose должен быть persistent volume. Для полного восстановления нужны и PostgreSQL, и OpenTofu state.

## Первичная настройка Proxmox

После запуска:

1. проверьте доступ к Proxmox API;
2. откройте **Control -> Golden Images**;
3. убедитесь, что список QEMU templates загружается;
4. создайте хотя бы один профиль, например `redos8`;
5. убедитесь, что карточка показывает `ready` и реальные CPU/RAM/disk/node/storage;
6. только после этого запускайте первый `tofu-proxmox` scenario.

Подробно: [Golden Images](/ru/operations/golden-images) и [Proxmox и OpenTofu](/ru/operations/proxmox-opentofu).

## Reverse proxy

Публикуйте наружу только reverse proxy, завершайте на нём TLS и ограничьте доступ к административным URL. Текущий cookie не выставляет `Secure`, поэтому проверьте политику прокси и считайте это известным техническим долгом.

Перед тем как открыть пользователям доступ к порталу:

- настройте TLS и не отключайте проверку сертификатов;
- задайте длинное случайное значение для подписи сессий;
- смените первоначальный пароль администратора;
- используйте отдельные сервисные учётные записи для внешних систем;
- не показывайте Proxmox token через UI, логи или scenario params;
- если используется старый callback hub, убедитесь, что runner имеет доступ к `ARACHNE_URL`;
- настройте резервное копирование PostgreSQL и OpenTofu state volume.

Также проверьте:

- часовой пояс контейнера, если используются cron-триггеры;
- доступ Arachne к Forgejo API, Nexus, Proxmox API и целевым узлам Ansible;
- наличие настоящих playbook и `tofu`, чтобы dev fallback не выдал фиктивный результат;
- достаточность `FORGEJO_DEADLINE` для самых долгих сборок;
- что ссылка Actions artifact открывается у нужных пользователей;
- что golden images имеют QEMU Guest Agent и DHCP;
- что resource overrides проверены на вашей версии `bpg/proxmox`.

## Первый интеграционный прогон стенда

Порядок проверки после развёртывания:

```text
Golden Image ready
  -> обычный provision
  -> IP/VM ID в artifact
  -> managed_machines row
  -> manual destroy
  -> lifetime: 2m
  -> auto destroy
  -> CPU/RAM override
  -> disk growth
```

Не начинайте с одновременно включённых TTL, disk resize и downstream Ansible. Сначала докажите базовый clone/destroy, затем добавляйте слои по одному.

## Обновление

```bash
git pull --ff-only
docker compose up -d --build
docker compose logs --tail=200 arachne
```

После обновления, затрагивающего Golden Images или lifecycle:

```bash
docker compose exec db \
  psql -U arachne -d arachne \
  -c '\d managed_machines'
```

Затем откройте **Control -> Golden Images** и убедитесь, что сохранённые profiles по-прежнему проходят live discovery.

`make update` выполняет примерно тот же цикл, но Makefile предполагает, что рабочий `docker-compose.yml` уже существует.
