# Установка

## Требования

- Docker Engine с Compose v2;
- Git;
- свободный порт `8080`;
- доступ от контейнера Arachne к PostgreSQL и подключаемым системам;
- доверенный корневой сертификат, если Forgejo или Nexus используют внутренний CA.

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

Первый пользователь — `admin`. Пароль берётся из `ADMIN_PASSWORD` только при
создании учётной записи. Изменение переменной после первого старта пароль в базе
не меняет.

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

Полный список переменных — в [справочнике конфигурации](/ru/reference/configuration).

## Внутренний центр сертификации

Не выключайте TLS-проверку просто потому, что сертификат внутренний. Положите CA
в каталог `certs/`, который Compose монтирует в `/etc/ssl/certs/`, и проверьте
значения `SSL_CERT_FILE` и `REQUESTS_CA_BUNDLE`.

`FORGEJO_VERIFY_TLS=false` годится для короткого локального эксперимента. В
эксплуатации это аккуратная кнопка «сделать MITM штатной функцией».

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
