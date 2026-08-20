(() => {
  const STEP_MARK = /^━+ step '([^']+)' via (\S+) ━+/;
  const GROUP_START = /^(?:::group::|##\[group\])(.+)$/;
  const GROUP_END = /^(?:::endgroup::|##\[endgroup\])\s*$/;
  const TASK_MARK = /^(TASK|PLAY|PLAY RECAP|RUNNING HANDLER)\b(?:\s*\[(.*?)\])?/;
  const NX_MARK = /^>\s+nx\s+run\s+(.+)$/i;

  function escapeSelector(value) {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  }

  function nearBottom(el) {
    return el.scrollHeight - el.scrollTop - el.clientHeight < 36;
  }

  function viewerFor(element) {
    return element && element.closest('.log-viewer');
  }

  function setFollowing(viewer, enabled) {
    viewer.dataset.follow = enabled ? 'true' : 'false';
    viewer.classList.toggle('is-following', enabled);
    const button = viewer.querySelector('[data-log-action="follow"]');
    if (button) button.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    if (enabled) {
      viewer.dataset.unseen = '0';
      updateNewLines(viewer);
      const scroll = viewer.querySelector('.log-scroll');
      if (scroll) scroll.scrollTop = scroll.scrollHeight;
    }
  }

  function updateNewLines(viewer) {
    const count = Number(viewer.dataset.unseen || 0);
    const button = viewer.querySelector('.log-new-lines');
    if (!button) return;
    button.textContent = count === 1 ? '1 new line ↓' : `${count} new lines ↓`;
    button.classList.toggle('is-visible', count > 0);
  }

  function updateCount(viewer) {
    const total = viewer.querySelectorAll('.log-line').length;
    const target = viewer.querySelector('.log-line-count');
    if (target) target.textContent = `${total} line${total === 1 ? '' : 's'}`;
  }

  function currentTarget(viewer) {
    return viewer._arachneTarget || viewer.querySelector('.log-lines');
  }

  function resetTarget(viewer) {
    viewer._arachneTarget = viewer.querySelector('.log-lines');
    viewer._arachneExplicitGroups = [];
    viewer._arachneImplicitGroup = null;
  }

  function createGroup(viewer, title, options = {}) {
    const details = document.createElement('details');
    details.className = 'log-group';
    if (options.live) details.classList.add('is-live-group');
    details.open = options.open !== false;

    const summary = document.createElement('summary');
    summary.textContent = title.trim() || 'output';
    const body = document.createElement('div');
    body.className = 'log-group-body';
    details.append(summary, body);

    currentTarget(viewer).appendChild(details);
    return { details, body };
  }

  function openExplicitGroup(viewer, title) {
    const group = createGroup(viewer, title, { live: viewer.classList.contains('is-live'), open: true });
    viewer._arachneExplicitGroups ||= [];
    viewer._arachneExplicitGroups.push(group);
    viewer._arachneTarget = group.body;
  }

  function closeExplicitGroup(viewer) {
    const groups = viewer._arachneExplicitGroups || [];
    const group = groups.pop();
    if (group) group.details.classList.remove('is-live-group');
    viewer._arachneTarget = groups.length
      ? groups[groups.length - 1].body
      : (viewer._arachneImplicitGroup?.body || viewer.querySelector('.log-lines'));
  }

  function openImplicitGroup(viewer, title) {
    if ((viewer._arachneExplicitGroups || []).length) return false;
    if (viewer._arachneImplicitGroup) {
      viewer._arachneImplicitGroup.details.classList.remove('is-live-group');
    }
    viewer._arachneTarget = viewer.querySelector('.log-lines');
    const group = createGroup(viewer, title, { live: viewer.classList.contains('is-live'), open: true });
    viewer._arachneImplicitGroup = group;
    viewer._arachneTarget = group.body;
    return true;
  }

  function appendVisualLine(viewer, text, stream = 'stdout') {
    const lineNo = Number(viewer.dataset.nextLine || 1);
    viewer.dataset.nextLine = String(lineNo + 1);

    const row = document.createElement('div');
    row.className = `log-line stream-${stream || 'stdout'}`;
    row.id = `${viewer.id || 'log'}-L${lineNo}`;
    row.dataset.raw = text;

    const number = document.createElement('a');
    number.className = 'log-line-number';
    number.href = `#${row.id}`;
    number.textContent = String(lineNo);
    number.title = `Line ${lineNo}`;

    const content = document.createElement('span');
    content.className = 'log-line-text';
    content.textContent = text;

    row.append(number, content);
    currentTarget(viewer).appendChild(row);
    updateCount(viewer);

    const scroll = viewer.querySelector('.log-scroll');
    if (viewer.dataset.follow === 'true' && scroll) {
      requestAnimationFrame(() => { scroll.scrollTop = scroll.scrollHeight; });
    } else if (viewer.classList.contains('is-live')) {
      viewer.dataset.unseen = String(Number(viewer.dataset.unseen || 0) + 1);
      updateNewLines(viewer);
    }
  }

  function appendLine(viewer, text, stream = 'stdout') {
    if (!viewer) return;
    const groupStart = text.match(GROUP_START);
    if (groupStart) {
      openExplicitGroup(viewer, groupStart[1]);
      return;
    }
    if (GROUP_END.test(text)) {
      closeExplicitGroup(viewer);
      return;
    }

    const task = text.match(TASK_MARK);
    if (task) {
      const title = task[2] || task[1].replace(/\b\w/g, c => c.toUpperCase());
      if (openImplicitGroup(viewer, title)) return;
    }
    const nx = text.match(NX_MARK);
    if (nx && openImplicitGroup(viewer, `nx ${nx[1]}`)) return;

    appendVisualLine(viewer, text, stream);
    applySearch(viewer);
  }

  function applySearch(viewer) {
    const input = viewer.querySelector('[data-log-search]');
    const counter = viewer.querySelector('.log-search-count');
    if (!input || !counter) return;
    const query = input.value.trim().toLocaleLowerCase();
    let matches = 0;
    viewer.querySelectorAll('.log-line').forEach(line => {
      const hit = query && (line.dataset.raw || '').toLocaleLowerCase().includes(query);
      line.classList.toggle('is-match', Boolean(hit));
      if (hit) matches += 1;
    });
    counter.textContent = query ? `${matches} hit${matches === 1 ? '' : 's'}` : '';
  }

  async function copyLog(viewer) {
    const text = Array.from(viewer.querySelectorAll('.log-line'))
      .map(line => line.dataset.raw || line.querySelector('.log-line-text')?.textContent || '')
      .join('\n');
    try {
      await navigator.clipboard.writeText(text);
      const button = viewer.querySelector('[data-log-action="copy"]');
      if (!button) return;
      const previous = button.innerHTML;
      button.classList.add('copied');
      button.innerHTML = '<i class="ti ti-check"></i> Copied';
      setTimeout(() => {
        button.classList.remove('copied');
        button.innerHTML = previous;
      }, 1200);
    } catch (error) {
      console.warn('Arachne log copy failed', error);
    }
  }

  function hydrateExisting(viewer) {
    resetTarget(viewer);
    const lines = Array.from(viewer.querySelectorAll('.log-line'));
    let max = 0;
    lines.forEach((line, index) => {
      const number = Number(line.querySelector('.log-line-number')?.textContent || index + 1);
      max = Math.max(max, number);
      line.dataset.raw ||= line.querySelector('.log-line-text')?.textContent || '';
    });
    viewer.dataset.nextLine = String(max + 1);
    viewer.dataset.unseen ||= '0';
    viewer.dataset.follow ||= 'true';
    viewer.classList.toggle('is-following', viewer.dataset.follow === 'true');
    updateCount(viewer);
  }

  function initViewer(viewer) {
    if (viewer.dataset.logReady === 'true') return;
    viewer.dataset.logReady = 'true';
    hydrateExisting(viewer);

    const scroll = viewer.querySelector('.log-scroll');
    if (scroll) {
      scroll.addEventListener('scroll', () => {
        if (nearBottom(scroll)) setFollowing(viewer, true);
        else if (viewer.dataset.follow === 'true') setFollowing(viewer, false);
      }, { passive: true });
    }

    viewer.querySelector('[data-log-search]')?.addEventListener('input', () => applySearch(viewer));
    viewer.querySelector('[data-log-action="wrap"]')?.addEventListener('click', event => {
      viewer.classList.toggle('is-wrapped');
      event.currentTarget.setAttribute('aria-pressed', viewer.classList.contains('is-wrapped') ? 'true' : 'false');
    });
    viewer.querySelector('[data-log-action="follow"]')?.addEventListener('click', () => {
      setFollowing(viewer, viewer.dataset.follow !== 'true');
    });
    viewer.querySelector('[data-log-action="copy"]')?.addEventListener('click', () => copyLog(viewer));
    viewer.querySelector('.log-new-lines')?.addEventListener('click', () => setFollowing(viewer, true));
  }

  function makeToolbar() {
    const toolbar = document.createElement('div');
    toolbar.className = 'log-toolbar';
    toolbar.innerHTML = `
      <div class="log-toolbar-main">
        <span class="log-live-state">Live</span>
        <span class="log-line-count">0 lines</span>
      </div>
      <input class="log-search" type="search" placeholder="Search log…" data-log-search aria-label="Search log">
      <span class="log-search-count"></span>
      <button class="log-tool" type="button" data-log-action="wrap" aria-pressed="false" title="Toggle line wrapping"><i class="ti ti-text-wrap"></i> Wrap</button>
      <button class="log-tool" type="button" data-log-action="follow" aria-pressed="true" title="Follow live output"><i class="ti ti-arrow-down"></i> Follow</button>
      <button class="log-tool" type="button" data-log-action="copy" title="Copy log"><i class="ti ti-copy"></i> Copy</button>`;
    return toolbar;
  }

  function createViewer(stepId, live = true) {
    const viewer = document.createElement('div');
    viewer.className = `log-viewer${live ? ' is-live is-following' : ''}`;
    viewer.id = `log-${stepId.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
    viewer.dataset.stepId = stepId;
    viewer.dataset.follow = 'true';
    viewer.innerHTML = `
      <div class="log-scroll">
        <div class="log-lines"></div>
        <button class="log-new-lines" type="button">0 new lines ↓</button>
      </div>`;
    viewer.prepend(makeToolbar());
    initViewer(viewer);
    return viewer;
  }

  function findStep(runRoot, stepId) {
    return Array.from(runRoot.querySelectorAll('.thread-step')).find(step =>
      step.querySelector('.step-title')?.textContent.trim() === stepId
    );
  }

  function ensureStep(runRoot, stepId, spider = '') {
    let step = findStep(runRoot, stepId);
    if (step) return step;

    step = document.createElement('div');
    step.className = 'thread-step running';
    step.innerHTML = `
      <span class="thread-node"></span>
      <div class="step-shell">
        <button type="button" class="step-head">
          <span class="step-head-main">
            <i class="ti ti-chevron-right step-chevron open"></i>
            <span class="step-title"></span>
            <span class="step-spider"></span>
          </span>
          <span class="step-summary">running…</span>
        </button>
        <div class="step-body"></div>
      </div>`;
    step.querySelector('.step-title').textContent = stepId;
    step.querySelector('.step-spider').textContent = spider;
    const body = step.querySelector('.step-body');
    body.appendChild(createViewer(stepId, true));
    step.querySelector('.step-head').addEventListener('click', () => {
      body.classList.toggle('hidden');
      step.querySelector('.step-chevron').classList.toggle('open');
    });
    runRoot.querySelector('.thread-timeline')?.appendChild(step);
    return step;
  }

  function activateStep(runRoot, stepId, spider = '') {
    runRoot.querySelectorAll('.thread-step.running').forEach(step => {
      if (step.querySelector('.step-title')?.textContent.trim() !== stepId) {
        step.classList.remove('running');
        step.classList.add('passed');
        const summary = step.querySelector('.step-summary');
        if (summary) summary.textContent = `${step.querySelectorAll('.log-line').length} lines`;
      }
    });
    const step = ensureStep(runRoot, stepId, spider);
    step.classList.remove('passed', 'pending');
    step.classList.add('running');
    const body = step.querySelector('.step-body');
    body?.classList.remove('hidden');
    step.querySelector('.step-chevron')?.classList.add('open');
    return step.querySelector('.log-viewer');
  }

  function prepareLiveView(runRoot) {
    runRoot.querySelectorAll('.log-viewer').forEach(viewer => {
      viewer.classList.add('is-live', 'is-following');
      const lines = viewer.querySelector('.log-lines');
      if (lines) lines.replaceChildren();
      resetTarget(viewer);
      viewer.dataset.nextLine = '1';
      viewer.dataset.unseen = '0';
      updateCount(viewer);
    });
  }

  async function refreshFinalMetadata(runRoot) {
    const url = runRoot.dataset.finalViewUrl;
    if (!url) return;
    try {
      const response = await fetch(url, { headers: { 'HX-Request': 'true' } });
      if (!response.ok) return;
      const html = await response.text();
      const doc = new DOMParser().parseFromString(html, 'text/html');
      const finalRoot = doc.querySelector(`#${escapeSelector(runRoot.id)}`) || doc.body.firstElementChild;
      const currentStatus = runRoot.querySelector('.run-status');
      const finalStatus = finalRoot?.querySelector('.run-status');
      if (currentStatus && finalStatus) currentStatus.replaceWith(finalStatus);

      runRoot.querySelectorAll('.thread-step').forEach(step => {
        const id = step.querySelector('.step-title')?.textContent.trim();
        const finalStep = id ? findStep(finalRoot, id) : null;
        if (!finalStep) return;
        step.className = finalStep.className;
        const summary = step.querySelector('.step-summary');
        const finalSummary = finalStep.querySelector('.step-summary');
        if (summary && finalSummary) summary.textContent = finalSummary.textContent;
      });

      const actions = runRoot.querySelector('.run-actions');
      const finalActions = finalRoot?.querySelector('.run-actions');
      if (actions && finalActions) actions.replaceWith(finalActions);

      const finalArtifacts = finalRoot?.querySelector('.run-final-artifacts');
      if (finalArtifacts && !runRoot.querySelector('.run-final-artifacts')) {
        runRoot.querySelector('.run-actions')?.before(finalArtifacts);
      }
    } catch (error) {
      console.warn('Arachne final run refresh failed', error);
    }
  }

  function initRun(runRoot) {
    if (!runRoot || runRoot.dataset.liveReady === 'true') return;
    runRoot.dataset.liveReady = 'true';
    runRoot.querySelectorAll('.log-viewer').forEach(initViewer);

    if (runRoot.dataset.liveRun !== 'true' || !runRoot.dataset.streamUrl) return;
    prepareLiveView(runRoot);

    let activeViewer = runRoot.querySelector('.thread-step.running .log-viewer')
      || runRoot.querySelector('.log-viewer');
    const source = new EventSource(runRoot.dataset.streamUrl);
    runRoot._arachneEventSource = source;

    source.onmessage = event => {
      const text = event.data;
      const mark = text.match(STEP_MARK);
      if (mark) {
        activeViewer = activateStep(runRoot, mark[1], mark[2]);
        return;
      }
      if (!activeViewer) activeViewer = activateStep(runRoot, 'output', '');
      appendLine(activeViewer, text, /^error\b|^fatal\b|ARACHNE ERROR/i.test(text) ? 'stderr' : 'stdout');
    };

    source.addEventListener('done', () => {
      source.close();
      runRoot.dataset.liveRun = 'false';
      runRoot.querySelectorAll('.log-viewer').forEach(viewer => {
        viewer.classList.remove('is-live');
        viewer.querySelectorAll('.log-group.is-live-group').forEach(group => group.classList.remove('is-live-group'));
        const live = viewer.querySelector('.log-live-state');
        if (live) live.textContent = 'Complete';
      });
      refreshFinalMetadata(runRoot);
    });

    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) return;
      runRoot.querySelectorAll('.log-live-state').forEach(el => { el.textContent = 'Reconnecting'; });
    };
  }

  function init(root = document) {
    root.querySelectorAll?.('.log-viewer').forEach(initViewer);
    root.querySelectorAll?.('[data-live-run]').forEach(initRun);
  }

  document.addEventListener('DOMContentLoaded', () => init());
  document.body.addEventListener('htmx:afterSwap', event => init(event.target));
  window.ArachneLogViewer = { init, appendLine };
})();
