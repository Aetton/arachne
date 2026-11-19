const { cpSync, mkdirSync, rmSync } = require('node:fs');
const { execFileSync } = require('node:child_process');

const output = 'frontend/static/vendor';
rmSync(output, { recursive: true, force: true });
mkdirSync(output, { recursive: true });

const assets = {
  'htmx.org/dist/htmx.min.js': 'htmx.min.js',
  '@tabler/icons-webfont/dist/tabler-icons.min.css': 'tabler/tabler-icons.min.css',
  '@tabler/icons-webfont/dist/fonts': 'tabler/fonts',
  'codemirror/theme/dracula.css': 'codemirror-dracula.css',
  'codemirror/theme/nord.css': 'codemirror-nord.css',
  '@fontsource/inconsolata/400.css': 'inconsolata/400.css',
  '@fontsource/inconsolata/500.css': 'inconsolata/500.css',
  '@fontsource/inconsolata/600.css': 'inconsolata/600.css',
  '@fontsource/inconsolata/700.css': 'inconsolata/700.css',
  '@fontsource/inconsolata/files': 'inconsolata/files',
  'js-yaml/dist/js-yaml.min.js': 'js-yaml.min.js',
  'monaco-editor/min/vs': 'monaco/vs',
};

for (const [source, destination] of Object.entries(assets)) {
  cpSync(`node_modules/${source}`, `${output}/${destination}`, { recursive: true });
}

execFileSync(process.execPath, [
  require.resolve('tailwindcss/lib/cli.js'),
  '--content', 'frontend/templates/**/*.html,frontend/static/js/**/*.js',
  '--output', `${output}/tailwind.css`,
  '--minify',
], { stdio: 'inherit' });
