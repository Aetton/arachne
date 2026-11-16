import { readFile, readdir, stat } from 'node:fs/promises';
import { resolve, join } from 'node:path';

const out = resolve(import.meta.dirname, '../out');
const prefix = (process.env.DOCS_BASE_PATH || '').replace(/\/$/, '');
const checks = [
  ['reference homepage', 'docs/ru/index.html', ['Справочник Arachne', 'Сценарии', 'Golden Images']],
  ['spider reference', 'docs/ru/reference/spiders/index.html', ['Пауки', 'forgejo', 'tofu-proxmox']],
  ['operator guide', 'docs/ru/user-guide/operator/index.html', ['оператор']],
  ['decision links', 'docs/ru/decisions/index.html', [prefix + '/docs/ru/decisions/20261116-unified-documentation']],
  ['English reference', 'docs/index.html', ['Arachne Documentation']],
  ['root redirect', 'index.html', [prefix + '/docs/ru/']],
  ['legacy redirect', 'ru/reference/spiders/index.html', [prefix + '/docs/ru/reference/spiders/']],
];
let failed = 0;
for (const [name, file, markers] of checks) {
  try {
    const html = await readFile(join(out, file), 'utf8');
    for (const marker of markers) {
      if (!html.toLowerCase().includes(marker.toLowerCase())) {
        throw new Error('missing content: ' + marker);
      }
    }
    console.log('PASS ' + name + ': ' + file);
  } catch (error) {
    console.error('FAIL ' + name + ': ' + file + ': ' + error.message);
    failed++;
  }
}
try {
  const search = await stat(join(out, 'api/search'));
  if (!search.isFile()) throw new Error('search index is not a file');
  console.log('PASS static search index');
} catch (error) {
  console.error('FAIL static search: ' + error.message);
  failed++;
}
// Catch exports whose content is present but whose assets or search use another base.
try {
  const html = await readFile(join(out, 'docs/ru/index.html'), 'utf8');
  const assets = [...html.matchAll(/(?:src|href)="([^"?#]*\/_next\/[^"?#]+)(?:[?#][^"]*)?"/g)]
    .map(match => match[1]);
  if (!assets.length) throw new Error('no Next assets found');
  for (const url of new Set(assets)) {
    if (!url.startsWith(prefix + '/_next/')) throw new Error('wrong asset prefix: ' + url);
    await stat(join(out, url.slice(prefix.length)));
  }
  const sidebarLink = 'href="' + prefix + '/docs/ru/reference/spiders';
  if (!html.includes(sidebarLink)) throw new Error('navigation is missing configured prefix');
  async function hasSearchClient(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const file = join(dir, entry.name);
      if (entry.isDirectory() && await hasSearchClient(file)) return true;
      if (entry.isFile() && file.endsWith('.js') &&
          (await readFile(file, 'utf8')).includes(prefix + '/api/search')) return true;
    }
    return false;
  }
  if (!await hasSearchClient(join(out, '_next'))) {
    throw new Error('search client is missing configured prefix');
  }
  console.log('PASS asset files, navigation and search client prefix');
} catch (error) {
  console.error('FAIL export paths: ' + error.message);
  failed++;
}
if (failed) process.exitCode = 1;
