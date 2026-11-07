import { readdir, mkdir, writeFile } from 'node:fs/promises';
import { join, resolve, relative } from 'node:path';

const root = resolve(import.meta.dirname, '../../docs');
const out = resolve(import.meta.dirname, '../out');
const basePath = (process.env.DOCS_BASE_PATH || '').replace(/\\/$/, '');

async function walk(path) {
  for (const item of await readdir(path, { withFileTypes: true })) {
    if (item.name.startsWith('.')) continue;
    const current = join(path, item.name);
    if (item.isDirectory()) {
      await walk(current);
    } else if (item.isFile() && item.name.endsWith('.md')) {
      const src = relative(root, current).replaceAll('\\\\', '/').replace(/\\.md$/, '');
      const slug = src.replace(/\\/index$/, '');
      const oldDir = slug === 'index' ? out : join(out, slug);
      // The new documentation lives under /docs; old nested URLs keep working.
      if (slug === 'index') continue; // Next.js already generated the root redirect.
      await mkdir(oldDir, { recursive: true });
      const target = `${basePath}/docs/${slug}/`;
      await writeFile(join(oldDir, 'index.html'),
        `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=${target}"><link rel="canonical" href="${target}"></head><body><a href="${target}">Перейти в документацию</a></body></html>\n`);
    }
  }
}
await walk(root);
console.log('Generated compatibility redirects for legacy documentation URLs.');
