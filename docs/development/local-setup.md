# Local development

```bash
cp .env.example .env
make up
make logs
```

Documentation is isolated in this directory:

```bash
cd docs
npm ci
npm run docs:dev
```

Build the documentation with `npm run docs:build`.
