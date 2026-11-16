const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const read = name => fs.readFileSync(path.join(__dirname, '../frontend/static/js', name), 'utf8');

function boot() {
  const dom = new JSDOM('<form id="scenario-form"></form><textarea id="scenario-definition"></textarea><div id="scenario-editor"></div><div id="scenario-editor-status"><span></span></div><script type="application/json" id="scenario-dsl-metadata"></script>', {
    url: 'http://localhost/admin/scenarios/new', runScripts: 'outside-only',
  });
  const win = dom.window;
  win.document.getElementById('scenario-dsl-metadata').textContent = JSON.stringify({spiders: [{name: 'custom-initial'}], triggers: ['manual'], param_types: ['string']});
  let text = 'steps:\n  - id: first\n    spider: ';
  let provider;
  const model = {
    getValue: () => text,
    getLineContent: n => text.split('\n')[n - 1],
    getLineCount: () => text.split('\n').length,
    getLineMaxColumn: n => text.split('\n')[n - 1].length + 1,
    getWordUntilPosition: () => ({startColumn: 1}),
    onDidChangeContent() {},
  };
  win.monaco = {
    languages: {register() {}, setMonarchTokensProvider() {}, CompletionItemKind: {Property: 1},
      registerCompletionItemProvider(_language, value) { provider = value; }},
    editor: {defineTheme() {}, createModel: () => model, create: () => ({addCommand() {}}), setModelMarkers() {}},
    Range: function () {}, KeyMod: {CtrlCmd: 1}, KeyCode: {KeyS: 1}, MarkerSeverity: {Error: 1},
  };
  win.require = (_modules, callback) => callback();
  win.require.config = () => {};
  win.jsyaml = {load: () => ({label: 'test', component: 'test', steps: [{id: 'first', spider: 'custom-initial', action: 'command'}]})};
  win.eval(read('scenario-dsl-catalog.js'));
  win.eval(read('scenario-editor.js'));
  return {dom, win, complete(value) {
    text = value;
    return Array.from(provider.provideCompletionItems(model, {lineNumber: text.split('\n').length, column: text.split('\n').at(-1).length + 1}).suggestions, item => item.insertText);
  }};
}

test('Monaco completion uses the installed catalog and sees live refreshes', () => {
  const {dom, win, complete} = boot();
  try {
    assert.deepEqual(complete('steps:\n  - id: first\n    spider: '), ['custom-initial']);
    win.arachneDslCatalog.set({spiders: [{name: 'custom-updated'}], triggers: ['event'], param_types: ['boolean']});
    assert.deepEqual(complete('steps:\n  - id: first\n    spider: '), ['custom-updated']);
    assert.deepEqual(complete('params:\n  - name: first\n    type: '), ['boolean']);
    assert.deepEqual(complete('triggers:\n  - type: '), ['event']);
  } finally { dom.window.close(); }
});

test('theme script keeps normalization, persistence and global handlers', () => {
  const dom = new JSDOM('<select id="theme-select"><option>white</option><option>nord</option></select>', {url: 'http://localhost', runScripts: 'outside-only'});
  try {
    dom.window.localStorage.setItem('arachne-theme', 'light');
    dom.window.eval(read('theme.js'));
    assert.equal(dom.window.document.documentElement.dataset.theme, 'white');
    dom.window.setTheme('nord');
    assert.equal(dom.window.document.documentElement.dataset.theme, 'nord');
    assert.equal(dom.window.localStorage.getItem('arachne-theme'), 'nord');
  } finally { dom.window.close(); }
});
