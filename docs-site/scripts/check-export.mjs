import { readFile, stat } from 'node:fs/promises';
import { resolve, join } from 'node:path';

const out = resolve(import.meta.dirname, '../out');
const prefix = (process.env.DOCS_BASE_PATH || '').replace(/\/$/, '');
const checks = [
  ['reference homepage', 'docs/ru/index.html', ['Справочник Arachne', 'Сценарии', 'Golden Images']],
  ['spider reference', 'docs/ru/reference/spiders/index.html', ['Пауки', 'forgejo', 'tofu-proxmox']],
  ['operator guide', 'docs/ru/user-guide/operator/index.html', ['оператор']],
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
if (failed) process.exitCode = 1;
