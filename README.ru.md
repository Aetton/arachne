# Arachne

Arachne — портал, который запускает CI/CD- и инфраструктурные сценарии из одного
места. Оператор выбирает сценарий, заполняет форму и видит ход работы, логи и
артефакты. Сборкой и развёртыванием занимаются Forgejo Actions, Ansible, OpenTofu
или другой подключённый исполнитель.

## Что уже работает

- сценарии и компоненты хранятся в базе;
- у сценариев есть версии, публикация, восстановление и YAML-экспорт;
- параметры запуска бывают строками, флагами, списками и динамическими списками веток;
- шаги выполняются последовательно и передают друг другу артефакты;
- встроены пауки `forgejo`, `ansible-local`, `tofu-proxmox`, `ansible-ovirt` и `scenario`;
- есть ручные, cron- и цепочечные запуски;
- логи приходят в интерфейс вживую и группируются по шагам;
- роли, команды и ACL решают, кто видит и запускает конкретный сценарий;
- PostgreSQL используется для постоянных данных, NATS можно включить как внешнюю шину.

## Быстрый старт

```bash
git clone https://github.com/Aetton/arachne.git
cd arachne
cp .env.example .env
cp docker-compose.yml.example docker-compose.yml
docker compose up -d --build
docker compose logs -f arachne
```

Откройте `http://localhost:8080`. При первом старте создаётся пользователь `admin`.
Его пароль берётся из `ADMIN_PASSWORD`.

Перед сетевым развёртыванием обязательно замените `JWT_SECRET`,
`ADMIN_PASSWORD` и `POSTGRES_PASSWORD`. При `ENV=prod` или `ENV=production`
приложение откажется стартовать с небезопасным `JWT_SECRET`.

## Куда идти дальше

- [Обзор и словарь](docs/ru/getting-started/overview.md)
- [Установка](docs/ru/getting-started/installation.md)
- [Работа оператора](docs/ru/user-guide/operator.md)
- [Администрирование](docs/ru/user-guide/administration.md)
- [Полный синтаксис сценариев](docs/ru/reference/scenario-syntax.md)
- [Пауки](docs/ru/reference/spiders.md)
- [Интеграция с Forgejo](docs/ru/integrations/forgejo.md)
- [Конфигурация](docs/ru/reference/configuration.md)
- [Развёртывание и резервное копирование](docs/ru/operations/deployment.md)
- [Что пока не работает или работает с оговорками](docs/ru/reference/limitations.md)

Собранная VitePress-документация доступна внутри контейнера по адресу `/wiki/`.

## Лицензия

Apache License 2.0. Подробности — в `LICENSE` и `NOTICE`.
