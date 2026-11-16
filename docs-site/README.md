# Arachne documentation (Fumadocs)

The canonical content remains in `../docs/**/*.md`. This Next.js application
generates a navigable, searchable Fumadocs reference during build.

## Local development

Requires Node.js 22 or later.

```bash
cd docs-site
npm ci
npm run dev
```

Production export:

```bash
DOCS_BASE_PATH=/arachne npm run build
DOCS_BASE_PATH=/arachne npm run check:export
```

The generated static files are in `docs-site/out/`.

## Content updates

Edit `docs/**/*.md` (NOT `docs-site/content/docs`). The sync step regenerates
Fumadocs frontmatter, navigation metadata, and links. The VitePress
configuration has been removed. Both the container and GitHub Pages use this build.

The old published root URL `/arachne/` now links to `/arachne/docs/ru/`.
Legacy links such as `/wiki/ru/reference/spiders` and `/arachne/ru/reference/spiders`
are preserved by redirects generated during the build.

## QA

- Confirm the Fumadocs left sidebar shows the full tree on all pages.
- Confirm right-side per-page TOC and full-text static search.
- Validate direct deep links on GitHub Pages and language navigation.
- Run `npm run check:links` after content sync.

## Container export

```bash
DOCS_BASE_PATH=/wiki npm run build
DOCS_BASE_PATH=/wiki npm run check:export
```

`DOCS_BASE_PATH` sets asset, navigation, redirect, and search request paths.
The public search prefix is derived automatically from this value.
The container copies `out/` to `/app/wiki/`, served by FastAPI at `/wiki/`.
