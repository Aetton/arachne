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

## Автоматическое обновление из GitHub

Workflow `Update Arachne build` запускается **после каждого push в `main`** на self-hosted runner и вызывает `just update` в каталоге развёртывания.

- По умолчанию включено. Для отключения задайте репозиторную переменную GitHub Actions `ARACHNE_AUTO_DEPLOY=false` (**Settings → Secrets and variables → Actions → Variables**).
- Вернуть автообновление можно, удалив переменную либо задав `ARACHNE_AUTO_DEPLOY=true`.
- `ARACHNE_DEPLOY_DIR` (по умолчанию `/opt/arachne`) и `ARACHNE_COMPOSE_COMMAND` (по умолчанию `docker compose`) задаются там же.
- Ручной запуск через **Actions → Update Arachne build → Run workflow** доступен даже при отключённом автодеплое.
- На runner должны быть установлены `just`, `git` и Docker Compose. Рабочая копия должна находиться на ветке `main` и не содержать локальных изменений отслеживаемых файлов.

Одновременно выполняется только один деплой. Ошибка `git pull --ff-only` останавливает сборку, чтобы не выкатывать устаревший код. Сам workflow не трогает `.env` и не выполняет `docker compose down -v`.

**Важно:** GitHub Actions запускает сборку от имени пользователя self-hosted runner, которому уже предоставлен доступ к Docker. Не назначайте runner недоверенным репозиториям и pull request workflows.

## Настройки URLs и перезапуск из Control

В **Control → Settings** можно переопределять URL Forgejo, GitLab, Nexus, Арахны, legacy Proxmox, адрес NATS, владельца Forgejo, профиль Koji, TLS-флаги и backend шины. Эти значения пишутся в PostgreSQL с аудитом, имеют приоритет над `.env`, но вступают в силу **после перезапуска Арахны**. Конфигурация подхватывается до импорта приложения и спайдеров. Кнопка **«Сброс»** возвращает значение из исходного окружения при следующем перезапуске.

Для кнопки **«Перезапустить Арахну»** необходим официальный однопроцессный Docker-режим (`python -m serve` как PID 1), `restart: unless-stopped` и переменная контейнера:

```yaml
services:
  arachne:
    restart: unless-stopped
    environment:
      ARACHNE_SELF_RESTART_ENABLED: "true"
```

После изменения Compose необходимо один раз пересоздать контейнер (`just update` или `docker compose up -d --force-recreate`). Кнопка отправляет SIGTERM процессу PID 1 **после HTTP-ответа**, и Docker запускает контейнер снова. При отсутствии конфигурации кнопка недоступна; используйте `just restart` на хосте.

**Осторожно:** перезапуск прерывает активные задания. Задачи, требующие непрерывности, завершите до подтверждения. Для Kubernetes, systemd и многопроцессной конфигурации нужна отдельная интеграция с соответствующим менеджером сервисов. Нельзя открывать Docker socket приложению ради кнопки перезапуска.

Секреты, пароль БД, master key и параметры, управляемые экранами Secrets/Ansible/Гипервизоры, остаются за пределами общего редактора.

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

`just update` выполняет примерно тот же цикл, но justfile предполагает, что рабочий `docker-compose.yml` уже существует.
