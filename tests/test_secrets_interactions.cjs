const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {JSDOM} = require('jsdom');
const root = path.join(__dirname, '..');
const html = execFileSync('python', ['-c', `
from jinja2 import Environment, FileSystemLoader, select_autoescape
from types import SimpleNamespace
env=Environment(loader=FileSystemLoader('frontend/templates'), autoescape=select_autoescape(['html']))
print(env.get_template('admin/secrets.html').render(
    user=dict(username='admin', roles=['admin']),
    request=SimpleNamespace(url=SimpleNamespace(path='/admin/secrets')),
    providers=[dict(slug='local',label='Local',kind='database',enabled=True,config={})],
    credentials=[],bindings=[]))
`], {cwd: root, encoding: 'utf8'});

function secrets() {
  const dom = new JSDOM(html, {url: 'http://localhost/admin/secrets', runScripts: 'outside-only'});
  dom.window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  dom.window.eval(fs.readFileSync(path.join(root, 'frontend/static/js/secrets.js'), 'utf8'));
  return dom;
}

test('extracted Secrets handlers keep dialog steps and credential defaults', () => {
  const dom = secrets();
  const win = dom.window;
  const byId = id => win.document.getElementById(id);
  try {
    win.openCredential('ssh');
    assert.equal(byId('credential-dialog').open, true);
    assert.equal(byId('credential-step-2').hidden, true);
    byId('credential-label').value = 'My access';
    win.advanceCredential();
    assert.equal(byId('credential-step-2').hidden, false);
    assert.equal(byId('credential-slug').value, 'my-access');
    assert.equal(byId('credential-secret-ref').value, 'credentials/my-access');
    assert.equal(byId('credential-port').value, '22');
    win.showSecretPanel('storage');
    assert.equal(byId('secrets-panel-storage').hidden, false);
    assert.equal(byId('secrets-panel-credentials').hidden, true);
    win.openProvider();
    assert.equal(byId('provider-dialog').open, true);
    assert.equal(byId('provider-kind').value, 'database');
  } finally { win.close(); }
});
