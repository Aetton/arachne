# Arachne documentation (Fumadocs)

The canonical content remains in `../docs/**/*.md`. This Next.js application
generates a navigable, searchable Fumadocs reference during build.

## Local development

Requires Node.js 22 or later.

```bash
cd docs-site
npm install
npm run dev
```

Production export:

```bash
DOCS_BASE_PATH=/arachne npm run build
```

The generated static files are in `docs-site/out/`.

## Content updates

Edit `docs/**/*.md` (NOT `docs-site/content/docs`). The sync step regenerates
Fumadocs frontmatter, navigation metadata, and links. The old VitePress
configuration remains for reference during migration but is no longer deployed.

The old published root URL `/arachne/` now links to `/arachne/docs/ru/`.
Existing deep links to `/arachne/ru/...` require redirects to remain compatible;
those are not yet implemented in this migration PR.

## QA

- Confirm the Fumadocs left sidebar shows the full tree on all pages.
- Confirm right-side per-page TOC and full-text static search.
- Validate direct deep links on GitHub Pages and language navigation.
- Run `npm run check:links` after content sync.
