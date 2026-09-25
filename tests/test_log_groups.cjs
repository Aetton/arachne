// Requires jsdom: npm install --no-save jsdom
// Run: node --test tests/test_log_groups.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const scripts = path.join(__dirname, '../frontend/static/js');
const stamp = '2026-09-25T11:42:03.2164065Z ';
function setup() {
  const dom = new JSDOM('<body><div class="log-viewer" data-follow="false" data-rebuild-groups="true"><div class="log-lines"></div></div></body>', {runScripts:'outside-only'});
  dom.window.eval(fs.readFileSync(path.join(scripts, 'live-log-viewer.js'), 'utf8'));
  const viewer = dom.window.document.querySelector('.log-viewer');
  return {dom, viewer, append: text => dom.window.ArachneLogViewer.appendLine(viewer, text)};
}
function titles(root) { return Array.from(root.querySelectorAll('.log-group > summary'), x => x.textContent); }
function lines(root) { return Array.from(root.querySelectorAll('.log-line'), x => x.dataset.raw); }

test('timestamped and ANSI-wrapped Forgejo markers form nested groups', () => {
  const {dom, viewer, append} = setup();
  [stamp+'##[group]Checkout', '\x1b[32m'+stamp+'::group::Fetch\x1b[0m', stamp+'payload', stamp+'::endgroup::', stamp+'##[endgroup]', 'tail'].forEach(append);
  assert.deepEqual(titles(viewer), ['Checkout','Fetch']);
  assert.equal(viewer.querySelectorAll('.log-group .log-group').length, 1);
  assert.deepEqual(lines(viewer.querySelector('.log-group .log-group')), [stamp+'payload']);
  assert.equal(viewer.querySelector('.log-lines > .log-line').dataset.raw, 'tail');
  assert.equal(viewer._arachneExplicitGroups.length, 0);
  dom.window.close();
});

test('Starting stages are siblings inside the explicit step and stop at its end', () => {
  const {dom, viewer, append} = setup();
  ['::group::Job', '::group::Step', stamp+'Starting: Compile', 'one', stamp+'Starting: Package', 'two', '::endgroup::', 'after step', '::endgroup::', 'after job'].forEach(append);
  const job = viewer.querySelector('.log-lines > .log-group');
  const step = job.querySelector('.log-group-body > .log-group');
  assert.deepEqual(titles(step), ['Step','Compile','Package']);
  assert.equal(step.querySelectorAll(':scope > .log-group-body > .log-group').length, 2);
  assert.deepEqual(lines(step), [stamp+'Starting: Compile','one',stamp+'Starting: Package','two']);
  assert.equal(job.querySelector(':scope > .log-group-body > .log-line').dataset.raw, 'after step');
  assert.equal(viewer.querySelector('.log-lines > .log-line').dataset.raw, 'after job');
  dom.window.close();
});

test('nested explicit group restores its containing implicit stage', () => {
  const {dom, viewer, append} = setup();
  ['Starting: Build', '::group::Inner', 'inside', '::endgroup::', 'back', 'Starting: Upload', 'next'].forEach(append);
  assert.deepEqual(titles(viewer), ['Build','Inner','Upload']);
  assert.equal(viewer.querySelectorAll('.log-lines > .log-group').length, 2);
  assert.deepEqual(lines(viewer.querySelector('.log-group')), ['Starting: Build','inside','back']);
  dom.window.close();
});

test('marker matching stays anchored; empty groups and unmatched ends are safe', () => {
  const {dom, viewer, append} = setup();
  ['Starting: Build','::endgroup::','echo ##[group]not a marker','::group::','x','::endgroup::'].forEach(append);
  assert.deepEqual(titles(viewer), ['Build','output']);
  assert.ok(lines(viewer).includes('echo ##[group]not a marker'));
  dom.window.close();
});

test('historical hydration produces the same grouping as streaming and is idempotent', () => {
  const input = ['::group::Job',stamp+'##[group]Checkout','git output',stamp+'##[endgroup]',stamp+'Starting: Compile','build output','::endgroup::'];
  const live = setup(), saved = setup();
  input.forEach(live.append);
  for (const text of input) {
    const row = saved.dom.window.document.createElement('div');
    row.className = 'log-line'; row.dataset.raw = text;
    saved.viewer.querySelector('.log-lines').append(row);
  }
  saved.dom.window.eval(fs.readFileSync(path.join(scripts,'log-group-hydrator.js'),'utf8'));
  const fire = () => saved.dom.window.document.dispatchEvent(new saved.dom.window.Event('DOMContentLoaded'));
  fire(); fire();
  assert.deepEqual(titles(saved.viewer), titles(live.viewer));
  assert.deepEqual(lines(saved.viewer), lines(live.viewer));
  live.dom.window.close(); saved.dom.window.close();
});

if (process.env.ARACHNE_LOG_FIXTURE) test('uploaded Forgejo log: seven checkout groups and six build stages', () => {
  const {dom, viewer, append} = setup();
  const input = fs.readFileSync(process.env.ARACHNE_LOG_FIXTURE,'utf8').trimEnd().split(/\r?\n/);
  input.forEach(append);
  assert.equal(titles(viewer).length, 13);
  assert.ok(titles(viewer).includes('Build RPM and source RPM'));
  assert.equal(viewer._arachneExplicitGroups.length, 0);
  assert.equal(lines(viewer).length, input.length - 14);
  assert.ok(lines(viewer).includes(input.find(x=>x.includes('Starting: Build Linux executable'))));
  dom.window.close();
});


test('timestamped Ansible and nx boundaries still group inside wrappers', () => {
  const {dom, viewer, append} = setup();
  ['::group::Job',stamp+'TASK [Install] ****','installed',stamp+'PLAY RECAP ****','recap',stamp+'> nx run app:build','built','::endgroup::'].forEach(append);
  assert.deepEqual(titles(viewer), ['Job','Install','PLAY RECAP','nx app:build']);
  assert.deepEqual(lines(viewer), ['installed','recap','built']);
  dom.window.close();
});

test('actual spider deltas resume stages across polls and matrix jobs', () => {
  const {execFileSync} = require('node:child_process');
  const batches = JSON.parse(execFileSync('python', ['-c', `
import sys,json
sys.path.insert(0, 'api')
from plugins.spiders.forgejo import ForgejoSpider

def snap(a,b):
 return '\\n'.join(['::group::Job A','::group::Step',*a,'::endgroup::','::endgroup::','::group::Job B',*b,'::endgroup::'])
first=snap(['Starting: Compile','a1'],['b1'])
second=snap(['Starting: Compile','a1','a2','Starting: Package','a3'],['b1','b2'])
third=snap(['Starting: Compile','a1','a2','Starting: Package','a3','a4'],['b1','b2'])
cursor={}
print(json.dumps([ForgejoSpider._new_log_lines('',first,cursor),ForgejoSpider._new_log_lines(first,second,cursor),ForgejoSpider._new_log_lines(second,third,cursor)]))
`], {cwd:path.join(__dirname,'..'), encoding:'utf8'}));
  const live=setup(), saved=setup();
  batches.flat().forEach(live.append);
  assert.deepEqual(titles(live.viewer), ['Job A','Step','Compile','Package','Job B']);
  const groups=Array.from(live.viewer.querySelectorAll('.log-group'));
  const group=title=>groups.find(x=>x.querySelector('summary').textContent===title);
  assert.deepEqual(lines(group('Compile')), ['Starting: Compile','a1','a2']);
  assert.deepEqual(lines(group('Package')), ['Starting: Package','a3','a4']);
  assert.deepEqual(lines(group('Job B')), ['b1','b2']);
  for(const raw of batches.flat()) {
    const row=saved.dom.window.document.createElement('div');
    row.className='log-line'; row.dataset.raw=raw;
    saved.viewer.querySelector('.log-lines').append(row);
  }
  saved.dom.window.eval(fs.readFileSync(path.join(scripts,'log-group-hydrator.js'),'utf8'));
  saved.dom.window.document.dispatchEvent(new saved.dom.window.Event('DOMContentLoaded'));
  assert.deepEqual(titles(saved.viewer), titles(live.viewer));
  assert.deepEqual(lines(saved.viewer), lines(live.viewer));
  live.dom.window.close(); saved.dom.window.close();
});
