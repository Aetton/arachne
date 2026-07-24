# Установка

## Требования

- Docker с Compose
- GNU Make

## Локальный запуск

```bash
git clone https://github.com/Aetton/arachne.git
cd arachne
cp .env.example .env
make up
make logs
```

Откройте `http://localhost:8080`. Перед эксплуатацией замените все значения-заглушки
в `.env`, смените первоначальный пароль администратора и настройте TLS.
