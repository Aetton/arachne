import { readdir, mkdir, writeFile } from 'node:fs/promises';
import { join, resolve, relative } from 'node:path';

const root = resolve(import.meta.dirname, '../../docs');
const out = resolve(import.meta.dirname, '../out');
const basePath = (process.env.DOCS_BASE_PATH || '').replace(/\/$/, '');

async function walk(path) {
  for (const item of await readdir(path, { withFileTypes: true })) {
    if (item.name.startsWith('.')) continue;
    const current = join(path, item.name);
    if (item.isDirectory()) {
      await walk(current);
    } else if (item.isFile() && item.name.endsWith('.md')) {
      const src = relative(root, current).replaceAll('\\', '/');
      const name = src.slice(0, -3);
      const slug = name.endsWith('/index') ? name.slice(0, -6) : name;
      if (slug === 'index') continue;
      const oldDir = join(out, slug);
      await mkdir(oldDir, { recursive: true });
      const target = basePath + '/docs/' + slug + '/';
      const html = '<!doctype html><html lang="ru"><head><meta charset="utf-8">' +
        '<meta http-equiv="refresh" content="0;url=' + target + '">' +
        '<link rel="canonical" href="' + target + '"></head><body>' +
        '<a href="' + target + '">Перейти в документацию</a></body></html>\n';
      await writeFile(join(oldDir, 'index.html'), html);
    }
  }
}
await walk(root);
console.log('Generated compatibility redirects for legacy documentation URLs.');
