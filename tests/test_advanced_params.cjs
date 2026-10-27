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


test('advanced grid is hidden when closed, toggles by summary, and reveals on invalid', () => {
  const css = fs.readFileSync(path.join(__dirname, '../frontend/static/css/arachne.css'), 'utf8');
  const dom = new JSDOM('<style>' + css + '</style><form><details class="advanced-params" data-advanced-params><summary>Дополнительные настройки</summary><p>Help</p><div class="thread-fields"><input name="flags" required></div></details></form>', { runScripts: 'outside-only' });
  const { document } = dom.window;
  dom.window.eval(fs.readFileSync(path.join(__dirname, '../frontend/static/js/advanced-params.js'), 'utf8'));
  const details = document.querySelector('details');
  const fields = document.querySelector('.thread-fields');
  const visible = () => dom.window.getComputedStyle(fields).display;
  assert.equal(visible(), 'none');
  assert.equal(dom.window.getComputedStyle(document.querySelector('p')).display, 'none');
  document.querySelector('summary').click();
  assert.equal(details.open, true);
  assert.equal(visible(), 'grid');
  document.querySelector('summary').click();
  assert.equal(details.open, false);
  assert.equal(visible(), 'none');
  document.querySelector('form').checkValidity();
  assert.equal(details.open, true);
  assert.equal(visible(), 'grid');
  dom.window.close();
});
