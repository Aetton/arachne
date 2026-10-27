const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

test('HTMX-inserted advanced inputs reveal invalid fields and submit while collapsed', () => {
  const dom = new JSDOM('<main id="workspace"></main>', { runScripts: 'outside-only' });
  const { document } = dom.window;
  dom.window.eval(fs.readFileSync(path.join(__dirname, '../frontend/static/js/advanced-params.js'), 'utf8'));
  document.querySelector('#workspace').innerHTML = '<form><input name="version" value="1.2"><details data-advanced-params><summary>Advanced</summary><input name="flags" value="-race" required><input type="checkbox" name="debug" value="true" checked></details></form>';
  const form = document.querySelector('form');
  const section = document.querySelector('details');
  assert.equal(section.open, false);
  assert.deepEqual([...new dom.window.FormData(form)], [['version', '1.2'], ['flags', '-race'], ['debug', 'true']]);
  form.elements.flags.value = '';
  assert.equal(form.checkValidity(), false);
  assert.equal(section.open, true);
  form.elements.flags.value = '-trimpath';
  section.open = false;
  assert.equal(form.checkValidity(), true);
  assert.equal(section.open, false);
  assert.equal(new dom.window.FormData(form).get('flags'), '-trimpath');
  dom.window.close();
});
