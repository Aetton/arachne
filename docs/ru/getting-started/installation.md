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
- сервисный API token, сохранённый в `Control -> Secrets`;
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

Первый пользователь: `admin`. Пароль берётся из `ADMIN_PASSWORD` только при создании
учётной записи. Изменение переменной после первого старта пароль в базе не меняет.

## Что остаётся в `.env`

Для локальной пробы достаточно bootstrap roots и connection configuration:

```dotenv
JWT_SECRET=длинная-случайная-строка
ADMIN_PASSWORD=отдельный-первоначальный-пароль
POSTGRES_PASSWORD=пароль-базы

ARACHNE_MASTER_KEY_SOURCE=env
ARACHNE_MASTER_KEY_REF=ARACHNE_MASTER_KEY
ARACHNE_MASTER_KEY=отдельный-master-key

FORGEJO_URL=https://forgejo.example.internal
FORGEJO_OWNER=example
FORGEJO_VERIFY_TLS=true

PROXMOX_VE_ENDPOINT=https://pve.example.internal:8006/
PROXMOX_VE_INSECURE=false
```

Токены Forgejo, GitLab, Proxmox и логин/пароль Nexus в `.env` больше не хранятся.
После старта откройте **Control -> Secrets**:

1. создайте Vault или encrypted DB provider;
2. создайте credentials нужных типов;
3. в `Infrastructure bindings` выберите credentials для Forgejo, GitLab, Proxmox VE и Nexus.

Для Vault bootstrap auth provider может ссылаться на env или mounted file с token/AppRole secret-id.

## Доступ Brood -> Ansible

Чтобы `ansible-local` мог использовать VM, созданную Brood/OpenTofu, Brood target
должен содержать `credentials_ref` на credential из `Control -> Secrets`.

Для Linux/SSH создайте credential типа `ssh`:

```text
Name: RedOS 8 deploy
Type: ssh
Username: root
Private key: <write-only>
```

Вместо private key можно использовать password. Container содержит `sshpass`.

Для Windows создайте credential типа `winrm` с username/password. В image установлен
`pywinrm`.

Во время запуска `ansible-local` сам создаёт временный inventory и, при необходимости,
private-key/known_hosts files. Secret material не передаётся через scenario YAML или
command-line arguments и удаляется после run.

## Ansible playbook repository

В `Control -> Ansible` настройте repository URL, ref, subdir и cache directory. Для
private repository выберите `git-ssh` или `git-token` credential из `Control -> Secrets`.

## OpenTofu provider mirror

Если прямой доступ к Terraform/OpenTofu provider registry ограничен:

```dotenv
TOFU_PROVIDER_MIRROR=https://tf-proxy.selectel.ru/mirror/v1/
```

Compose передаст переменную в контейнер, а entrypoint создаст `/root/.tofurc`.

## Golden Images

Не прописывайте VM ID шаблонов, node, datastore и disk metadata в `.env`. После старта
они настраиваются через **Control -> Golden Images**, а фактические характеристики
template читаются через Proxmox API.

## Внутренний центр сертификации

Не выключайте TLS-проверку просто потому, что сертификат внутренний.

Положите один или несколько корпоративных CA в каталог `certs/`. Каждый сертификат
должен быть отдельным файлом с расширением `.crt`.

Compose монтирует их в штатный trust store, а entrypoint выполняет
`update-ca-certificates`. Итоговый bundle:

```text
/etc/ssl/certs/ca-certificates.crt
```

Его используют `SSL_CERT_FILE` и `REQUESTS_CA_BUNDLE`.

## Проверка после запуска

```bash
curl -fsS http://localhost:8080/healthz
docker compose ps
docker compose logs --tail=100 arachne
```

Для OpenTofu:

```bash
docker compose exec arachne tofu version
```

Для Ansible target access после настройки credential полезно проверить полный сценарий:

```text
Brood provision -> Ansible playbook -> RunOutput
```

Подробности: [Конфигурация](/ru/reference/configuration), [Golden Images](/ru/operations/golden-images) и [Proxmox и OpenTofu](/ru/operations/proxmox-opentofu).
