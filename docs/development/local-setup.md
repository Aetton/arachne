# Local development

```bash
cp .env.example .env
just up
just logs
```

Markdown content lives in `docs/`; the Fumadocs builder lives in `docs-site/`:

```bash
cd docs-site
npm ci
npm run dev
```

Build with `npm run build`, then run `npm run check:export`. Use the same
`DOCS_BASE_PATH` for both commands: `/wiki` for the container or `/arachne`
for GitHub Pages. Omit it when serving from the site root.
