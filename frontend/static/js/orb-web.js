(function () {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var state = {
    selectedSpoke: null,
    selectedStatus: 'selected',
    selectedSource: null,
    scenarioByLabel: new Map(),
    scenarioBySlug: new Map(),
    runStatuses: new Map(),
    hasScannedRuns: false,
    lastImpulseAt: 0,
    logObserver: null
  };

  var geometry = {
    width: 1000,
    height: 760,
    hub: { x: 515, y: 310 },
    bounds: { left: 80, top: 34, right: 930, bottom: 610 },
    angles: [-168, -140, -112, -83, -36, -6, 26, 63, 106, 145],
    rings: [0.14, 0.24, 0.35, 0.47, 0.60, 0.74, 0.88]
  };

  var omittedSegments = new Set([
    '1:3', '1:7',
    '2:1', '2:5', '2:8',
    '3:2', '3:6',
    '4:0', '4:4', '4:8',
    '5:2', '5:5',
    '6:3', '6:6', '6:8'
  ]);

  function svgNode(tag, attrs) {
    var node = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach(function (key) {
      node.setAttribute(key, String(attrs[key]));
    });
    return node;
  }

  function hashText(value) {
    var text = String(value || 'arachne');
    var hash = 0;
    for (var i = 0; i < text.length; i += 1) {
      hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0;
    }
    return Math.abs(hash);
  }

  function pointAlong(angle, distance) {
    var radians = angle * Math.PI / 180;
    return {
      x: geometry.hub.x + Math.cos(radians) * distance,
      y: geometry.hub.y + Math.sin(radians) * distance
    };
  }

  function maxDistance(angle) {
    var radians = angle * Math.PI / 180;
    var dx = Math.cos(radians);
    var dy = Math.sin(radians);
    var candidates = [];
    if (dx > 0) candidates.push((geometry.bounds.right - geometry.hub.x) / dx);
    if (dx < 0) candidates.push((geometry.bounds.left - geometry.hub.x) / dx);
    if (dy > 0) candidates.push((geometry.bounds.bottom - geometry.hub.y) / dy);
    if (dy < 0) candidates.push((geometry.bounds.top - geometry.hub.y) / dy);
    return Math.min.apply(Math, candidates.filter(function (value) { return value > 0; }));
  }

  function midpointAngle(a1, a2) {
    var delta = ((a2 - a1 + 540) % 360) - 180;
    return a1 + delta / 2;
  }

  function capturePath(spokeA, spokeB, fraction) {
    var d1 = spokeA.max * fraction;
    var d2 = spokeB.max * fraction;
    var p1 = pointAlong(spokeA.angle, d1);
    var p2 = pointAlong(spokeB.angle, d2);
    var averageDistance = (d1 + d2) / 2;
    var control = pointAlong(midpointAngle(spokeA.angle, spokeB.angle), averageDistance * 1.075);
    var c1 = { x: p1.x + (control.x - p1.x) * 0.58, y: p1.y + (control.y - p1.y) * 0.58 };
    var c2 = { x: p2.x + (control.x - p2.x) * 0.58, y: p2.y + (control.y - p2.y) * 0.58 };
    return ['M', p1.x.toFixed(2), p1.y.toFixed(2), 'C', c1.x.toFixed(2), c1.y.toFixed(2), c2.x.toFixed(2), c2.y.toFixed(2), p2.x.toFixed(2), p2.y.toFixed(2)].join(' ');
  }

  function framePath(spokeA, spokeB) {
    var p1 = pointAlong(spokeA.angle, spokeA.max * 0.93);
    var p2 = pointAlong(spokeB.angle, spokeB.max * 0.91);
    var averageDistance = (spokeA.max + spokeB.max) * 0.47;
    var control = pointAlong(midpointAngle(spokeA.angle, spokeB.angle), averageDistance * 1.10);
    var c1 = { x: p1.x + (control.x - p1.x) * 0.52, y: p1.y + (control.y - p1.y) * 0.52 };
    var c2 = { x: p2.x + (control.x - p2.x) * 0.52, y: p2.y + (control.y - p2.y) * 0.52 };
    return 'M ' + p1.x.toFixed(2) + ' ' + p1.y.toFixed(2) + ' C ' + c1.x.toFixed(2) + ' ' + c1.y.toFixed(2) + ' ' + c2.x.toFixed(2) + ' ' + c2.y.toFixed(2) + ' ' + p2.x.toFixed(2) + ' ' + p2.y.toFixed(2);
  }

  function routePath(index) {
    if (index === null || index === undefined) return null;
    var angle = geometry.angles[index];
    if (angle === undefined) return null;
    var distance = maxDistance(angle) * 0.93;
    var end = pointAlong(angle, distance);
    return { d: 'M ' + end.x.toFixed(2) + ' ' + end.y.toFixed(2) + ' L ' + geometry.hub.x + ' ' + geometry.hub.y, entry: end };
  }

  function buildWeb(svg) {
    var spokes = geometry.angles.map(function (angle, index) { return { index: index, angle: angle, max: maxDistance(angle) }; });
    var frameGroup = svgNode('g', { class: 'orb-web-frame-group' });
    var webGroup = svgNode('g', { class: 'orb-web-base' });
    var captureGroup = svgNode('g', { class: 'orb-web-capture-group' });
    var junctionGroup = svgNode('g', { class: 'orb-web-junction-group' });
    var activeGroup = svgNode('g', { class: 'orb-web-active-group' });

    spokes.forEach(function (spoke) {
      var end = pointAlong(spoke.angle, spoke.max * 0.93);
      webGroup.appendChild(svgNode('path', { class: 'orb-web-spoke', 'data-spoke-index': spoke.index, d: 'M ' + geometry.hub.x + ' ' + geometry.hub.y + ' L ' + end.x.toFixed(2) + ' ' + end.y.toFixed(2) }));
    });

    geometry.rings.forEach(function (fraction, ringIndex) {
      spokes.forEach(function (spoke, index) {
        var nextIndex = (index + 1) % spokes.length;
        if (nextIndex === 0 && ringIndex > 3) return;
        if (omittedSegments.has(ringIndex + ':' + index)) return;
        var next = spokes[nextIndex];
        captureGroup.appendChild(svgNode('path', { class: 'orb-web-capture', 'data-spoke-a': index, 'data-spoke-b': nextIndex, d: capturePath(spoke, next, fraction) }));
        if ((ringIndex + index) % 5 === 0 && ringIndex > 0 && ringIndex < 5) {
          var junction = pointAlong(spoke.angle, spoke.max * fraction);
          junctionGroup.appendChild(svgNode('circle', { class: 'orb-web-junction', cx: junction.x.toFixed(2), cy: junction.y.toFixed(2), r: 2.25 }));
        }
      });
    });

    [0, 1, 3, 5, 7, 8].forEach(function (index) {
      var nextIndex = (index + 1) % spokes.length;
      frameGroup.appendChild(svgNode('path', { class: 'orb-web-frame', d: framePath(spokes[index], spokes[nextIndex]) }));
    });

    var hubGroup = svgNode('g', { class: 'orb-web-hub' });
    hubGroup.appendChild(svgNode('circle', { class: 'orb-web-hub-ring', cx: geometry.hub.x, cy: geometry.hub.y, r: 18 }));
    hubGroup.appendChild(svgNode('circle', { class: 'orb-web-hub-core', cx: geometry.hub.x, cy: geometry.hub.y, r: 8 }));
    svg.appendChild(frameGroup);
    svg.appendChild(webGroup);
    svg.appendChild(captureGroup);
    svg.appendChild(junctionGroup);
    svg.appendChild(activeGroup);
    svg.appendChild(hubGroup);
  }

  function syncHubPosition() {
    var workspace = document.querySelector('.operator-workspace');
    var svg = workspace && workspace.querySelector(':scope > .workspace-orb-web svg');
    if (!workspace || !svg || !svg.getScreenCTM) return;
    var matrix = svg.getScreenCTM();
    if (!matrix) return;
    var point = svg.createSVGPoint();
    point.x = geometry.hub.x;
    point.y = geometry.hub.y;
    var screenPoint = point.matrixTransform(matrix);
    var workspaceRect = workspace.getBoundingClientRect();
    workspace.style.setProperty('--orb-hub-x', (screenPoint.x - workspaceRect.left).toFixed(2) + 'px');
    workspace.style.setProperty('--orb-hub-y', (screenPoint.y - workspaceRect.top).toFixed(2) + 'px');
  }

  function ensureLayer() {
    var workspace = document.querySelector('.operator-workspace');
    if (!workspace) return null;
    var existing = workspace.querySelector(':scope > .workspace-orb-web');
    if (existing) { syncHubPosition(); return existing; }
    var layer = document.createElement('div');
    layer.className = 'workspace-orb-web';
    layer.setAttribute('aria-hidden', 'true');
    var svg = svgNode('svg', { viewBox: '0 0 ' + geometry.width + ' ' + geometry.height, preserveAspectRatio: 'xMidYMid slice' });
    buildWeb(svg);
    layer.appendChild(svg);
    workspace.insertBefore(layer, workspace.firstChild);
    window.requestAnimationFrame(syncHubPosition);
    return layer;
  }

  function apportionSectors(groups) {
    var totalSpokes = geometry.angles.length;
    var totalScenarios = groups.reduce(function (sum, group) { return sum + group.cards.length; }, 0) || 1;
    var shares = groups.map(function (group) {
      var raw = group.cards.length / totalScenarios * totalSpokes;
      return { group: group, raw: raw, count: Math.max(1, Math.floor(raw)), fraction: raw - Math.floor(raw) };
    });
    var used = shares.reduce(function (sum, item) { return sum + item.count; }, 0);

    while (used > totalSpokes) {
      var removable = shares.filter(function (item) { return item.count > 1; }).sort(function (a, b) { return a.fraction - b.fraction; });
      if (!removable.length) break;
      removable[0].count -= 1;
      used -= 1;
    }

    while (used < totalSpokes) {
      var receivers = shares.slice().sort(function (a, b) { return b.fraction - a.fraction; });
      receivers[0].count += 1;
      receivers[0].fraction = -1;
      used += 1;
    }

    var cursor = 0;
    shares.forEach(function (item) {
      item.spokes = [];
      for (var i = 0; i < item.count; i += 1) item.spokes.push((cursor + i) % totalSpokes);
      cursor += item.count;
    });
    return shares;
  }

  function buildSemanticMap() {
    state.scenarioByLabel.clear();
    state.scenarioBySlug.clear();
    var groups = Array.from(document.querySelectorAll('.scenario-group')).map(function (group) {
      return { component: group.dataset.component || 'default', cards: Array.from(group.querySelectorAll('.scenario-card')) };
    }).filter(function (group) { return group.cards.length; });

    apportionSectors(groups).forEach(function (sector) {
      sector.group.cards.forEach(function (card) {
        var slug = card.dataset.scenario || card.dataset.search || card.textContent;
        var labelNode = card.querySelector('.scenario-title');
        var label = (card.dataset.scenarioLabel || (labelNode && labelNode.textContent) || '').trim();
        var spoke = sector.spokes[hashText(slug) % sector.spokes.length];
        var semantic = { slug: slug, label: label, component: sector.group.component, spoke: spoke, card: card, sectorSpokes: sector.spokes.slice() };
        card.dataset.orbSpoke = String(spoke);
        card.dataset.orbSector = sector.spokes.join(',');
        state.scenarioBySlug.set(slug, semantic);
        if (label && !state.scenarioByLabel.has(label)) state.scenarioByLabel.set(label, semantic);
      });
    });
  }

  function resolveRun(row) {
    if (!row) return null;
    var title = row.querySelector('.run-row-title');
    var label = (row.dataset.scenarioLabel || (title && title.textContent) || '').trim();
    var semantic = state.scenarioByLabel.get(label);
    if (!semantic) return null;
    return { runId: row.dataset.runId || '', status: row.dataset.runStatus || (row.classList.contains('running') ? 'running' : 'selected'), spoke: semantic.spoke, scenario: semantic, row: row };
  }

  function statusClass(status) {
    if (status === 'success') return 'status-success';
    if (status === 'failed') return 'status-failed';
    if (status === 'cancelled') return 'status-cancelled';
    if (status === 'running') return 'status-running';
    return 'status-selected';
  }

  function appendRoute(group, spoke, status, options) {
    var route = routePath(spoke);
    if (!route) return;
    options = options || {};
    var cls = statusClass(status);
    var base = svgNode('path', { class: 'orb-web-route-base ' + cls + (options.selected ? ' is-selected' : ''), d: route.d });
    var pulse = svgNode('path', { class: 'orb-web-route-pulse ' + cls + (options.selected ? ' is-selected' : ''), d: route.d, pathLength: 100 });
    if (options.delay) pulse.style.animationDelay = options.delay + 's';
    group.appendChild(base);
    group.appendChild(pulse);
    group.appendChild(svgNode('circle', { class: 'orb-web-route-entry ' + cls, cx: route.entry.x.toFixed(2), cy: route.entry.y.toFixed(2), r: options.selected ? 5.5 : 4 }));
  }

  function renderRoutes() {
    var layer = ensureLayer();
    if (!layer) return;
    var active = layer.querySelector('.orb-web-active-group');
    if (!active) return;
    active.replaceChildren();
    Array.from(document.querySelectorAll('.run-row.running')).forEach(function (row, index) {
      var run = resolveRun(row);
      if (!run) return;
      row.dataset.orbSpoke = String(run.spoke);
      appendRoute(active, run.spoke, 'running', { delay: -(index * 0.43) });
    });
    if (state.selectedSpoke !== null) appendRoute(active, state.selectedSpoke, state.selectedStatus, { selected: true, delay: -0.2 });
    highlightSelection();
  }

  function highlightSelection() {
    var layer = document.querySelector('.operator-workspace > .workspace-orb-web');
    if (!layer) return;
    layer.querySelectorAll('.orb-web-spoke.is-selected, .orb-web-capture.is-selected').forEach(function (node) { node.classList.remove('is-selected'); });
    if (state.selectedSpoke === null) return;
    var spoke = layer.querySelector('.orb-web-spoke[data-spoke-index="' + state.selectedSpoke + '"]');
    if (spoke) spoke.classList.add('is-selected');
    layer.querySelectorAll('.orb-web-capture').forEach(function (path) {
      if (Number(path.dataset.spokeA) === state.selectedSpoke || Number(path.dataset.spokeB) === state.selectedSpoke) path.classList.add('is-selected');
    });
  }

  function emitImpulse(spoke, status) {
    if (spoke === null || spoke === undefined) return;
    var layer = ensureLayer();
    var active = layer && layer.querySelector('.orb-web-active-group');
    var route = routePath(spoke);
    if (!active || !route) return;
    var impulse = svgNode('path', { class: 'orb-web-event-impulse ' + statusClass(status || 'running'), d: route.d, pathLength: 100 });
    active.appendChild(impulse);
    impulse.addEventListener('animationend', function () { impulse.remove(); }, { once: true });
  }

  function clearRunSelection() {
    document.querySelectorAll('.run-row.web-route-selected').forEach(function (row) { row.classList.remove('web-route-selected'); });
  }

  function selectScenario(card) {
    clearRunSelection();
    var semantic = state.scenarioBySlug.get(card.dataset.scenario) || state.scenarioByLabel.get(card.dataset.scenarioLabel || '');
    if (!semantic) return;
    state.selectedSource = 'scenario';
    state.selectedSpoke = semantic.spoke;
    state.selectedStatus = 'selected';
    renderRoutes();
    emitImpulse(semantic.spoke, 'selected');
  }

  function selectRun(row) {
    document.querySelectorAll('.scenario-card.is-selected').forEach(function (card) { card.classList.remove('is-selected'); });
    clearRunSelection();
    row.classList.add('web-route-selected');
    var run = resolveRun(row);
    if (!run) return;
    state.selectedSource = 'run';
    state.selectedSpoke = run.spoke;
    state.selectedStatus = run.status;
    renderRoutes();
    emitImpulse(run.spoke, run.status);
  }

  function scanRunStatuses() {
    var next = new Map();
    document.querySelectorAll('.run-row[data-run-id]').forEach(function (row) {
      var run = resolveRun(row);
      var id = row.dataset.runId;
      var status = row.dataset.runStatus || 'unknown';
      next.set(id, status);
      var previous = state.runStatuses.get(id);
      if (state.hasScannedRuns && run && (!previous || previous !== status)) emitImpulse(run.spoke, status);
    });
    state.runStatuses = next;
    state.hasScannedRuns = true;
  }

  function observeLiveLog() {
    var workspace = document.querySelector('.operator-workspace');
    if (!workspace || state.logObserver) return;
    state.logObserver = new MutationObserver(function (mutations) {
      var hasLogLine = mutations.some(function (mutation) {
        if (!mutation.addedNodes.length) return false;
        if (mutation.target.closest && mutation.target.closest('.log-lines')) return true;
        return Array.from(mutation.addedNodes).some(function (node) {
          return node.nodeType === 1 && ((node.matches && node.matches('.log-line')) || (node.querySelector && node.querySelector('.log-line')));
        });
      });
      if (!hasLogLine || state.selectedSpoke === null) return;
      var now = Date.now();
      if (now - state.lastImpulseAt < 180) return;
      state.lastImpulseAt = now;
      emitImpulse(state.selectedSpoke, 'running');
    });
    state.logObserver.observe(workspace, { childList: true, subtree: true });
  }

  document.addEventListener('click', function (event) {
    var scenario = event.target.closest('.scenario-card');
    if (scenario) { selectScenario(scenario); return; }
    var run = event.target.closest('.run-row');
    if (run) selectRun(run);
  });

  document.body.addEventListener('htmx:afterSwap', function (event) {
    window.requestAnimationFrame(function () {
      ensureLayer();
      buildSemanticMap();
      syncHubPosition();
      if (event.target && event.target.id === 'run-list') {
        scanRunStatuses();
        renderRoutes();
      } else if (event.target && event.target.id === 'workspace') {
        if (event.target.querySelector('.artifact-block') && state.selectedSpoke !== null) emitImpulse(state.selectedSpoke, 'success');
        renderRoutes();
      }
    });
  });

  window.addEventListener('resize', function () {
    ensureLayer();
    window.requestAnimationFrame(syncHubPosition);
  }, { passive: true });

  ensureLayer();
  buildSemanticMap();
  observeLiveLog();
  window.requestAnimationFrame(function () {
    syncHubPosition();
    scanRunStatuses();
    renderRoutes();
  });
})();
