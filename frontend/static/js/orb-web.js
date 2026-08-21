(function () {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var state = {
    route: null,
    source: null
  };

  var geometry = {
    width: 1000,
    height: 760,
    hub: { x: 515, y: 310 },
    bounds: { left: 80, top: 34, right: 930, bottom: 610 },
    angles: [-168, -140, -112, -83, -36, -6, 26, 63, 106, 145],
    rings: [0.14, 0.24, 0.35, 0.47, 0.60, 0.74, 0.88],
    routeChoices: [0, 1, 9]
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
    var c1 = {
      x: p1.x + (control.x - p1.x) * 0.58,
      y: p1.y + (control.y - p1.y) * 0.58
    };
    var c2 = {
      x: p2.x + (control.x - p2.x) * 0.58,
      y: p2.y + (control.y - p2.y) * 0.58
    };

    return [
      'M', p1.x.toFixed(2), p1.y.toFixed(2),
      'C', c1.x.toFixed(2), c1.y.toFixed(2),
      c2.x.toFixed(2), c2.y.toFixed(2),
      p2.x.toFixed(2), p2.y.toFixed(2)
    ].join(' ');
  }

  function framePath(spokeA, spokeB) {
    var p1 = pointAlong(spokeA.angle, spokeA.max * 0.93);
    var p2 = pointAlong(spokeB.angle, spokeB.max * 0.91);
    var averageDistance = (spokeA.max + spokeB.max) * 0.47;
    var control = pointAlong(midpointAngle(spokeA.angle, spokeB.angle), averageDistance * 1.10);
    var c1 = {
      x: p1.x + (control.x - p1.x) * 0.52,
      y: p1.y + (control.y - p1.y) * 0.52
    };
    var c2 = {
      x: p2.x + (control.x - p2.x) * 0.52,
      y: p2.y + (control.y - p2.y) * 0.52
    };

    return 'M ' + p1.x.toFixed(2) + ' ' + p1.y.toFixed(2) +
      ' C ' + c1.x.toFixed(2) + ' ' + c1.y.toFixed(2) +
      ' ' + c2.x.toFixed(2) + ' ' + c2.y.toFixed(2) +
      ' ' + p2.x.toFixed(2) + ' ' + p2.y.toFixed(2);
  }

  function buildWeb(svg) {
    var spokes = geometry.angles.map(function (angle, index) {
      return { index: index, angle: angle, max: maxDistance(angle) };
    });

    var frameGroup = svgNode('g', { class: 'orb-web-frame-group' });
    var webGroup = svgNode('g', { class: 'orb-web-base' });
    var captureGroup = svgNode('g', { class: 'orb-web-capture-group' });
    var junctionGroup = svgNode('g', { class: 'orb-web-junction-group' });
    var activeGroup = svgNode('g', { class: 'orb-web-active-group' });

    spokes.forEach(function (spoke) {
      var end = pointAlong(spoke.angle, spoke.max * 0.93);
      webGroup.appendChild(svgNode('path', {
        class: 'orb-web-spoke',
        'data-spoke-index': spoke.index,
        d: 'M ' + geometry.hub.x + ' ' + geometry.hub.y + ' L ' + end.x.toFixed(2) + ' ' + end.y.toFixed(2)
      }));
    });

    geometry.rings.forEach(function (fraction, ringIndex) {
      spokes.forEach(function (spoke, index) {
        var nextIndex = (index + 1) % spokes.length;
        if (nextIndex === 0 && ringIndex > 3) return;
        if (omittedSegments.has(ringIndex + ':' + index)) return;

        var next = spokes[nextIndex];
        captureGroup.appendChild(svgNode('path', {
          class: 'orb-web-capture',
          d: capturePath(spoke, next, fraction)
        }));

        if ((ringIndex + index) % 5 === 0 && ringIndex > 0 && ringIndex < 5) {
          var junctionDistance = spoke.max * fraction;
          var junction = pointAlong(spoke.angle, junctionDistance);
          junctionGroup.appendChild(svgNode('circle', {
            class: 'orb-web-junction',
            cx: junction.x.toFixed(2),
            cy: junction.y.toFixed(2),
            r: 2.25
          }));
        }
      });
    });

    [0, 1, 3, 5, 7, 8].forEach(function (index) {
      var nextIndex = (index + 1) % spokes.length;
      frameGroup.appendChild(svgNode('path', {
        class: 'orb-web-frame',
        d: framePath(spokes[index], spokes[nextIndex])
      }));
    });

    activeGroup.appendChild(svgNode('path', { class: 'orb-web-active-base' }));
    activeGroup.appendChild(svgNode('path', { class: 'orb-web-active-pulse' }));
    activeGroup.appendChild(svgNode('circle', { class: 'orb-web-entry', r: 5 }));

    var hubGroup = svgNode('g', { class: 'orb-web-hub' });
    hubGroup.appendChild(svgNode('circle', {
      class: 'orb-web-hub-ring',
      cx: geometry.hub.x,
      cy: geometry.hub.y,
      r: 18
    }));
    hubGroup.appendChild(svgNode('circle', {
      class: 'orb-web-hub-core',
      cx: geometry.hub.x,
      cy: geometry.hub.y,
      r: 8
    }));

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
    if (existing) {
      syncHubPosition();
      return existing;
    }

    var layer = document.createElement('div');
    layer.className = 'workspace-orb-web';
    layer.setAttribute('aria-hidden', 'true');

    var svg = svgNode('svg', {
      viewBox: '0 0 ' + geometry.width + ' ' + geometry.height,
      preserveAspectRatio: 'xMidYMid slice'
    });
    buildWeb(svg);
    layer.appendChild(svg);
    workspace.insertBefore(layer, workspace.firstChild);

    applyRoute(state.route);
    window.requestAnimationFrame(syncHubPosition);
    return layer;
  }

  function spokePath(index) {
    if (index === null || index === undefined) return null;
    var angle = geometry.angles[index];
    if (angle === undefined) return null;
    var distance = maxDistance(angle) * 0.93;
    var end = pointAlong(angle, distance);
    return {
      d: 'M ' + end.x.toFixed(2) + ' ' + end.y.toFixed(2) + ' L ' + geometry.hub.x + ' ' + geometry.hub.y,
      entry: end
    };
  }

  function applyRoute(index) {
    var layer = document.querySelector('.operator-workspace > .workspace-orb-web');
    if (!layer) return;

    var base = layer.querySelector('.orb-web-active-base');
    var pulse = layer.querySelector('.orb-web-active-pulse');
    var entry = layer.querySelector('.orb-web-entry');
    var route = spokePath(index);

    if (!route) {
      base.setAttribute('d', '');
      pulse.setAttribute('d', '');
      entry.setAttribute('cx', '-50');
      entry.setAttribute('cy', '-50');
      return;
    }

    base.setAttribute('d', route.d);
    pulse.setAttribute('d', route.d);
    entry.setAttribute('cx', route.entry.x.toFixed(2));
    entry.setAttribute('cy', route.entry.y.toFixed(2));
  }

  function chooseRoute(seed) {
    var text = String(seed || 'arachne');
    var hash = 0;
    for (var i = 0; i < text.length; i += 1) {
      hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0;
    }
    return geometry.routeChoices[Math.abs(hash) % geometry.routeChoices.length];
  }

  function clearRunSelection() {
    document.querySelectorAll('.run-row.web-route-selected').forEach(function (row) {
      row.classList.remove('web-route-selected');
    });
  }

  function selectScenario(card) {
    clearRunSelection();
    state.source = 'scenario';
    state.route = chooseRoute(card.dataset.search || card.textContent);
    applyRoute(state.route);
  }

  function selectRun(row) {
    document.querySelectorAll('.scenario-card.is-selected').forEach(function (card) {
      card.classList.remove('is-selected');
    });
    clearRunSelection();
    row.classList.add('web-route-selected');
    state.source = 'run';
    state.route = chooseRoute(row.textContent);
    applyRoute(state.route);
  }

  function selectFirstLiveRunIfIdle() {
    if (state.source) return;
    var live = document.querySelector('.run-row.running');
    if (!live) return;
    selectRun(live);
  }

  document.addEventListener('click', function (event) {
    var scenario = event.target.closest('.scenario-card');
    if (scenario) {
      selectScenario(scenario);
      return;
    }

    var run = event.target.closest('.run-row');
    if (run) selectRun(run);
  });

  document.body.addEventListener('htmx:afterSwap', function (event) {
    window.requestAnimationFrame(function () {
      ensureLayer();
      applyRoute(state.route);
      syncHubPosition();
      if (event.target && event.target.id === 'run-list') selectFirstLiveRunIfIdle();
    });
  });

  window.addEventListener('resize', function () {
    ensureLayer();
    window.requestAnimationFrame(syncHubPosition);
  }, { passive: true });

  ensureLayer();
  window.requestAnimationFrame(function () {
    syncHubPosition();
    selectFirstLiveRunIfIdle();
  });
})();
