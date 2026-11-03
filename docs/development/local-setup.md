# Local development

```bash
cp .env.example .env
just up
just logs
```

Documentation is isolated in this directory:

```bash
cd docs
npm ci
npm run docs:dev
```

Build the documentation with `npm run docs:build`.
