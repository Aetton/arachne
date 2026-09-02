# Установка

## Требования

- Docker Engine с Compose v2;
- Git;
- свободный порт `8080`;
- доступ от контейнера Arachne к PostgreSQL и подключаемым системам;
- доверенный корневой сертификат, если Forgejo, Nexus или Proxmox используют внутренний CA.

Для `tofu-proxmox` дополнительно нужны:

- OpenTofu внутри контейнера Arachne;
- доступ к Proxmox VE API по HTTPS;
- сервисный API token;
- хотя бы один подготовленный QEMU template;
- QEMU Guest Agent в golden image.

## Локальный запуск

```bash
git clone https://github.com/Aetton/arachne.git
cd arachne
cp .env.example .env
cp docker-compose.yml.example docker-compose.yml
docker compose up -d --build
docker compose logs -f arachne
```

Откройте:

- портал: `http://localhost:8080`;
- документацию: `http://localhost:8080/wiki/`;
- OpenAPI: `http://localhost:8080/docs`;
- проверку живости: `http://localhost:8080/healthz`.

Первый пользователь - `admin`. Пароль берётся из `ADMIN_PASSWORD` только при создании учётной записи. Изменение переменной после первого старта пароль в базе не меняет.

## Что поменять в `.env`

Для локальной пробы достаточно задать bootstrap-значения:

```dotenv
JWT_SECRET=длинная-случайная-строка
ADMIN_PASSWORD=отдельный-первоначальный-пароль
POSTGRES_PASSWORD=пароль-базы
```

Если используется encrypted DB provider, задайте внешний master key или mounted file. Если используется Vault, его token/AppRole secret-id тоже остаётся bootstrap secret вне управляемого Vault namespace Arachne.

Сервисные credentials Forgejo, GitLab, Proxmox, Nexus и Git-доступ к Ansible playbook repository в `.env` не хранятся. После первого запуска откройте:

```text
Control -> Secrets
```

Создайте Provider (`Vault` или encrypted DB), затем Credential и назначьте его в `Service bindings`.

### Forgejo

В `.env` остаются только обычные настройки:

```dotenv
FORGEJO_URL=https://forgejo.example.internal
FORGEJO_OWNER=example
FORGEJO_VERIFY_TLS=true
```

В `Control -> Secrets` создайте credential типа `token` и назначьте его binding `Forgejo`.

### GitLab

```dotenv
GITLAB_URL=https://gitlab.example.internal
GITLAB_VERIFY_TLS=true
```

GitLab token хранится как credential типа `token` и назначается binding `GitLab`.

### Proxmox

В `.env` остаются только endpoint и TLS policy:

```dotenv
PROXMOX_VE_ENDPOINT=https://pve.example.internal:8006/
PROXMOX_VE_INSECURE=false
```

API token хранится как credential типа `token` и назначается binding `Proxmox VE`. Arachne материализует его в runtime для API client и OpenTofu provider.

### Nexus

В `.env` остаётся endpoint:

```dotenv
NEXUS_URL=https://nexus.example.internal
```

Логин и пароль хранятся как credential типа `basic` и назначаются binding `Nexus`.

Если Nexus upload выполняется внутри Forgejo/GitLab workflow, этот удалённый CI всё равно должен получить credential через собственный secret store. Arachne не пересылает секреты в workflow inputs автоматически.

Если прямой доступ к Terraform/OpenTofu provider registry ограничен, задайте network mirror:

```dotenv
TOFU_PROVIDER_MIRROR=https://tf-proxy.selectel.ru/mirror/v1/
```

Compose передаст переменную в контейнер, а entrypoint создаст `/root/.tofurc`. URL зеркала не зашит в Docker image и может быть заменён без пересборки кода.

Не прописывайте VM ID шаблонов, node, datastore и disk metadata в `.env`. После старта они настраиваются через **Control -> Golden Images**, а фактические характеристики template читаются через Proxmox API.

Полный список переменных - в [справочнике конфигурации](/ru/reference/configuration).

## Внутренний центр сертификации

Не выключайте TLS-проверку просто потому, что сертификат внутренний.

Положите один или несколько корпоративных CA в каталог `certs/`. Каждый сертификат должен быть отдельным файлом с расширением `.crt`, например:

```text
certs/
├── redsoft-root-ca.crt
└── redsoft-intermediate-ca.crt
```

Compose монтирует этот каталог в:

```text
/usr/local/share/ca-certificates/arachne/
```

При старте контейнера entrypoint запускает `update-ca-certificates`. Корпоративные CA добавляются в штатный Debian trust store вместе с публичными корневыми сертификатами.

Итоговый bundle:

```text
/etc/ssl/certs/ca-certificates.crt
```

Именно его используют `SSL_CERT_FILE` и `REQUESTS_CA_BUNDLE`.

Не монтируйте `certs/` поверх `/etc/ssl/certs/` и не указывайте `SSL_CERT_FILE` на одиночный корпоративный сертификат. Иначе системные публичные CA будут скрыты, и HTTPS к внешним registry, GitHub, PyPI и другим сервисам начнёт падать с `x509: certificate signed by unknown authority`.

`FORGEJO_VERIFY_TLS=false` или `PROXMOX_VE_INSECURE=true` годятся только для короткого локального эксперимента. В эксплуатации используйте доверенный CA.

### Проверка trust store

После запуска контейнера проверьте итоговый bundle:

```bash
docker compose exec arachne sh -lc '
  echo "$SSL_CERT_FILE"
  test -s /etc/ssl/certs/ca-certificates.crt
  ls -l /etc/ssl/certs/ca-certificates.crt
'
```

Публичный TLS:

```bash
docker compose exec arachne \
  curl -fsSI https://registry.terraform.io/
```

Если используется внутренний Proxmox CA:

```bash
docker compose exec arachne \
  curl -fsS "${PROXMOX_VE_ENDPOINT%/}/api2/json/version"
```

При корректном trust store должны работать одновременно и публичные, и внутренние HTTPS endpoints.

## Права Proxmox для клонирования стендов

Arachne должна получать только права, необходимые для клонирования и управления VM. Не выдавайте сервисной роли `Sys.Modify` только ради изменения Proxmox tags.

`tofu-proxmox` не управляет тегами клонированной VM. Набор тегов golden image остаётся как есть, поэтому зарегистрированные cluster tags не требуют `Sys.Modify` на `/`.

Для bridge из local SDN zone сервисной роли нужен `SDN.Use`. Для получения IP и сетевых интерфейсов из QEMU Guest Agent нужен `VM.GuestAgent.Audit`. `VM.GuestAgent.Unrestricted` для этой операции не требуется.

Остальные права зависят от операций, разрешённых конкретному deployment, но для текущего клонирования используются VM/Datastore privileges без административного доступа к кластерной конфигурации.

## Проверка после запуска

```bash
curl -fsS http://localhost:8080/healthz
docker compose ps
docker compose logs --tail=100 arachne
```

Ожидаемый ответ healthcheck:

```json
{"status":"ok"}
```

Если планируется OpenTofu provisioning:

```bash
docker compose exec arachne tofu version
```

Если настроен provider mirror:

```bash
docker compose exec arachne cat /root/.tofurc
```

После настройки `Control -> Secrets` и Proxmox binding откройте **Control -> Golden Images**. Если API token и TLS настроены правильно, страница должна показать доступные QEMU templates.

Первый рабочий профиль удобно создать как:

```text
Name: RedOS 8
Key:  redos8
OS:   redos8
```

После этого сценарий с `os: redos8` сможет использовать профиль без знания VM ID.

Подробно: [Golden Images](/ru/operations/golden-images).
