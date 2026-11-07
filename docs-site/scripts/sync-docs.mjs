import { readFile, writeFile, mkdir, readdir, rm } from 'node:fs/promises';
import { resolve, join, dirname, relative, extname } from 'node:path';

const here = resolve(import.meta.dirname, '..');
const source = resolve(here, '..', 'docs');
const target = resolve(here, 'content/docs');
const prefix = (process.env.DOCS_BASE_PATH || '').replace(/\/$/, '');
const sections = {
  root: ['ru', 'index', 'getting-started', 'user-guide', 'reference', 'hubs', 'architecture', 'development', 'operations', 'decisions'],
  ru: ['index', 'getting-started', 'user-guide', 'reference', 'integrations', 'architecture', 'development', 'operations', 'decisions'],
};
const titles = {
  ru: 'Русский · Справочник',
  'getting-started': 'Начало работы',
  'user-guide': 'Руководство пользователя',
  reference: 'Справочник',
  integrations: 'Интеграции',
  hubs: 'Интеграции',
  architecture: 'Архитектура',
  development: 'Разработка',
  operations: 'Эксплуатация',
  decisions: 'Решения',
};
const escape = (s) => JSON.stringify(s);
const home = {
  'index.md': '# Arachne Documentation\n\nChoose a section in the left navigation. The complete Russian reference is available in [Русский справочник](/ru/).\n\n## Getting started\n\n- [Overview](/getting-started/overview)\n- [First scenario](/getting-started/first-scenario)\n- [Scenario syntax](/reference/scenario-syntax)\n',
  'ru/index.md': '# Справочник Arachne\n\nЗдесь собраны инструкции по использованию, администрированию и разработке Арахны. **Полное дерево страниц всегда слева**, содержание текущей страницы справа.\n\n## С чего начать\n\n- [Обзор](/ru/getting-started/overview)\n- [Установка](/ru/getting-started/installation)\n- [Первый сценарий](/ru/getting-started/first-scenario)\n\n## Справочная информация\n\n- [Сценарии](/ru/user-guide/scenarios)\n- [DSL](/ru/reference/scenario-syntax)\n- [Пауки](/ru/reference/spiders)\n- [Права](/ru/user-guide/access)\n- [Golden Images](/ru/operations/golden-images)\n- [API](/ru/reference/api)\n',
};
async function scan(dir) {
  const result = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.name.startsWith('.')) continue;
    const path = join(dir, entry.name);
    if (entry.isDirectory()) result.push(...await scan(path));
    else if (entry.isFile() && extname(entry.name) === '.md') result.push(path);
  }
  return result;
}
function convert(raw, path) {
  const noFrontmatter = raw.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '');
  const match = noFrontmatter.match(/^\s*#\s+(.+)$/m);
  const title = match?.[1]?.replace(/[\u0060*]/g, '') || path.split('/').at(-1).replace(/\.md$/, '');
  const withoutHeading = match ? noFrontmatter.replace(/^\s*#\s+.+\r?\n/m, '') : noFrontmatter;
  const rewritten = withoutHeading.replace(/\]\(\/(?!\/)([^)]+)\)/g, (_, link) => {
    const [pathPart, hash] = link.split('#');
    const clean = pathPart.replace(/\.md$/, '').replace(/\/$/, '');
    return `](${prefix}/docs/${clean}${hash ? '#' + hash : ''})`;
  });
  return `---\ntitle: ${escape(title)}\n---\n\n${rewritten.trim()}\n`;
}
await rm(target, { recursive: true, force: true });
for (const file of await scan(source)) {
  const path = relative(source, file).replaceAll('\\', '/');
  const dest = join(target, path);
  await mkdir(dirname(dest), { recursive: true });
  await writeFile(dest, convert(home[path] ?? await readFile(file, 'utf8'), path));
}
async function addMeta(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const dirs = entries.filter((e) => e.isDirectory()).map((e) => e.name);
  const pages = entries.filter((e) => e.isFile() && e.name.endsWith('.md')).map((e) => e.name.replace(/\.md$/, ''));
  const rel = relative(target, dir).replaceAll('\\', '/');
  const preferred = sections[rel || 'root'] ?? (rel.startsWith('ru/') ? ['index'] : ['index']);
  const all = [...new Set([...preferred, ...dirs, ...pages])].filter((p) => dirs.includes(p) || pages.includes(p));
  const title = titles[rel.split('/').at(-1)];
  await writeFile(join(dir, 'meta.json'), JSON.stringify({ ...(title ? { title } : {}), pages: all }, null, 2) + '\n');
  for (const sub of dirs) await addMeta(join(dir, sub));
}
await addMeta(target);
console.log('Synchronized Markdown documentation into Fumadocs content tree.');
