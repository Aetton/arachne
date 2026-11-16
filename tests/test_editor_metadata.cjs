const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM, VirtualConsole} = require('jsdom');
const source = fs.readFileSync(path.join(__dirname, '../frontend/static/js/scenario-dsl-metadata.js'), 'utf8');

function catalog(name) {
  return {spiders: [{name, family: 'command', actions: ['command'], inputs: {custom_input: {description: 'Custom input'}}}]};
}

async function editor(refresh) {
  const dom = new JSDOM('<script type="application/json" id="scenario-dsl-metadata"></script><div class="dsl-reference"></div>', {
    url: 'http://localhost/admin/scenarios/new', runScripts: 'outside-only', virtualConsole: new VirtualConsole(),
  });
  dom.window.document.getElementById('scenario-dsl-metadata').textContent = JSON.stringify(catalog('installed-custom'));
  dom.window.fetch = url => url === '/api/admin/scenario-dsl' ? refresh() : Promise.reject(new Error('no repository'));
  dom.window.eval(source);
  await new Promise(resolve => dom.window.addEventListener('load', resolve, {once: true}));
  await new Promise(resolve => setTimeout(resolve, 0));
  return dom;
}

test('failed API refresh retains the server catalog without invented plugins', async () => {
  const dom = await editor(() => Promise.reject(new Error('offline')));
  try {
    const text = dom.window.document.querySelector('.dsl-reference').textContent;
    assert.match(text, /installed-custom/);
    assert.match(text, /custom_input/);
    assert.doesNotMatch(text, /forgejo|tofu-proxmox|ansible-local/);
  } finally { dom.window.close(); }
});

test('successful refresh replaces the initial installed catalog', async () => {
  const dom = await editor(() => Promise.resolve({ok: true, json: () => Promise.resolve(catalog('updated-custom'))}));
  try {
    const text = dom.window.document.querySelector('.dsl-reference').textContent;
    assert.match(text, /updated-custom/);
    assert.doesNotMatch(text, /installed-custom/);
  } finally { dom.window.close(); }
});
