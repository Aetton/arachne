import { readFile, readdir } from 'node:fs/promises';
import { join, resolve, relative, dirname } from 'node:path';
const docs = resolve(import.meta.dirname, '../../docs');
const paths = [];
async function walk(dir) {
  for (const e of await readdir(dir, { withFileTypes: true })) {
    const file = join(dir, e.name);
    if (e.isDirectory() && !e.name.startsWith('.')) await walk(file);
    else if (e.isFile() && e.name.endsWith('.md')) paths.push(file);
  }
}
await walk(docs);
const set = new Set(paths.map(p => relative(docs, p).replaceAll('\\', '/').replace(/\.md$/, '').replace(/\/index$/, '')));
let errors = 0;
for (const file of paths) {
  const text = await readFile(file, 'utf8');
  for (const match of text.matchAll(/\]\(\/([^#)]+)(?:#[^)]*)?\)/g)) {
    const target = match[1].replace(/\.md$/, '').replace(/\/$/, '');
    if (target && !set.has(target)) {
      console.error(`${relative(docs, file)}: broken absolute documentation link /${target}`);
      errors++;
    }
  }
}
if (errors) { console.error(`${errors} invalid links`); process.exitCode = 1; }
else console.log(`Checked ${paths.length} Markdown pages: no broken absolute documentation links.`);
