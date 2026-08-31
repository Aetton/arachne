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

- портал — `http://localhost:8080`;
- документацию — `http://localhost:8080/wiki/`;
- OpenAPI — `http://localhost:8080/docs`;
- проверку живости — `http://localhost:8080/healthz`.

Первый пользователь — `admin`. Пароль берётся из `ADMIN_PASSWORD` только при создании учётной записи. Изменение переменной после первого старта пароль в базе не меняет.

## Что поменять в `.env`

Для локальной пробы достаточно задать три значения:

```dotenv
JWT_SECRET=длинная-случайная-строка
ADMIN_PASSWORD=отдельный-первоначальный-пароль
POSTGRES_PASSWORD=пароль-базы
```

Для Forgejo добавьте:

```dotenv
FORGEJO_URL=https://forgejo.example.internal
FORGEJO_TOKEN=токен-сервисной-учётки
FORGEJO_OWNER=example
FORGEJO_VERIFY_TLS=true
```

Для Proxmox добавьте только параметры подключения:

```dotenv
PROXMOX_VE_ENDPOINT=https://pve.example.internal:8006/
PROXMOX_VE_API_TOKEN=arachne@pve!arachne=<TOKEN_SECRET>
PROXMOX_VE_INSECURE=false
```

Если прямой доступ к Terraform/OpenTofu registry ограничен, задайте provider mirror:

```dotenv
TOFU_PROVIDER_MIRROR=https://tf-proxy.selectel.ru/mirror/v1/
```

Это не зашито в Docker image. Compose передаёт значение в контейнер, а entrypoint при старте генерирует `/root/.tofurc`. URL можно заменить на любой совместимый OpenTofu/Terraform network mirror без пересборки образа.

Если `TOFU_PROVIDER_MIRROR` пуст, `.tofurc` удаляется и OpenTofu использует direct provider installation.

Для `tofu-proxmox` provider имеет явную identity `registry.terraform.io/bpg/proxmox` и фиксированную версию. Зеркало меняет только маршрут загрузки provider-а, а не его identity.

Не прописывайте VM ID шаблонов, node, datastore и disk metadata в `.env`. После старта они настраиваются через **Control -> Golden Images**, а фактические характеристики template читаются через Proxmox API.

Полный список переменных — в [справочнике конфигурации](/ru/reference/configuration).

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

Если настроен provider mirror, проверьте созданный CLI config:

```bash
docker compose exec arachne cat /root/.tofurc
```

Если используется внутренний Proxmox CA:

```bash
docker compose exec arachne \
  curl -fsS "${PROXMOX_VE_ENDPOINT%/}/api2/json/version"
```

При корректном trust store должны работать одновременно и публичные, и внутренние HTTPS endpoints.

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

После настройки Proxmox откройте **Control -> Golden Images**. Если API token и TLS настроены правильно, страница должна показать доступные QEMU templates.

Первый рабочий профиль удобно создать как:

```text
Name: RedOS 8
Key:  redos8
OS:   redos8
```

После этого сценарий с `os: redos8` сможет использовать профиль без знания VM ID.

Подробно: [Golden Images](/ru/operations/golden-images).
