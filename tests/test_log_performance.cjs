const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { JSDOM } = require('jsdom');
const code = fs.readFileSync(require('node:path').join(__dirname, '../frontend/static/js/live-log-viewer.js'), 'utf8');

test('appending logs does not rescan all rows and coalesces scrolling', () => {
  const dom = new JSDOM('<body><div class="log-viewer" data-follow="true"><input data-log-search><span class="log-search-count"></span><span class="log-line-count"></span><div class="log-scroll"><div class="log-lines"></div></div></div>', {runScripts:'outside-only'});
  let frames = 0;
  dom.window.requestAnimationFrame = () => ++frames;
  dom.window.eval(code);
  const viewer = dom.window.document.querySelector('.log-viewer');
  dom.window.ArachneLogViewer.init();
  const original = viewer.querySelectorAll.bind(viewer);
  viewer.querySelectorAll = selector => {
    assert.notEqual(selector, '.log-line', 'append must not scan old rows');
    return original(selector);
  };
  for (let i=0; i<1000; i++) dom.window.ArachneLogViewer.appendLine(viewer, `line ${i}`);
  assert.equal(viewer.querySelector('.log-line-count').textContent, '1000 lines');
  assert.equal(frames, 1);
  viewer.querySelectorAll = original;
  const search = viewer.querySelector('input');
  search.value = 'line 99';
  search.dispatchEvent(new dom.window.Event('input'));
  assert.equal(viewer.querySelectorAll('.is-match').length, 11);
  dom.window.ArachneLogViewer.appendLine(viewer, 'line 9999');
  assert.equal(viewer.querySelectorAll('.is-match').length, 12);
  dom.window.close();
});

test('removing a running view closes its EventSource even without new messages', async () => {
  const dom = new JSDOM('<body><div id="workspace"><div data-live-run="true" data-stream-url="/stream"><div class="thread-timeline"></div></div></div>', {runScripts:'outside-only'});
  let closed = 0;
  dom.window.EventSource = class { addEventListener() {} close() { closed++; } };
  dom.window.eval(code);
  dom.window.ArachneLogViewer.init();
  dom.window.document.querySelector('#workspace').innerHTML = '';
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(closed, 1);
  dom.window.close();
});
