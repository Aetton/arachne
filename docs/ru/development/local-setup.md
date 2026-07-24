# Локальная разработка

```bash
cp .env.example .env
make up
make logs
```

Инструменты документации изолированы в каталоге `docs`:

```bash
cd docs
npm ci
npm run docs:dev
```

Production-сборка документации запускается командой `npm run docs:build`.
