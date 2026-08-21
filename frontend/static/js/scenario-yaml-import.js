(function () {
  'use strict';

  var dialog = document.getElementById('scenario-import-dialog');
  var openButton = document.getElementById('scenario-import-open');
  var form = document.getElementById('scenario-import-form');
  var fileInput = document.getElementById('scenario-import-file');
  var modeInput = document.getElementById('scenario-import-mode');
  var status = document.getElementById('scenario-import-status');
  var submit = document.getElementById('scenario-import-submit');

  if (!dialog || !openButton || !form || !fileInput || !modeInput || !status || !submit) return;

  var slugPattern = /^[a-z0-9][a-z0-9._-]{0,63}$/;
  var permissions = ['view', 'run', 'edit', 'manage'];
  var parsedPayload = null;

  function setStatus(message, kind) {
    status.textContent = message || '';
    status.className = 'scenario-import-status' + (kind ? ' is-' + kind : '');
  }

  function asMapping(value, label) {
    if (value === null || value === undefined) return {};
    if (typeof value !== 'object' || Array.isArray(value)) {
      throw new Error(label + ' must be a mapping');
    }
    return value;
  }

  function parsePayload(text) {
    if (!window.jsyaml) throw new Error('YAML parser is unavailable');
    var payload = window.jsyaml.load(text) || {};
    payload = asMapping(payload, 'YAML root');
    var components = asMapping(payload.components, 'components');
    var scenarios = asMapping(payload.scenarios, 'scenarios');
    if (!Object.keys(components).length && !Object.keys(scenarios).length) {
      throw new Error('YAML contains neither components nor scenarios');
    }
    return { components: components, scenarios: scenarios };
  }

  function validateStep(step, slug, index) {
    if (!step || typeof step !== 'object' || Array.isArray(step)) {
      throw new Error(slug + ': step #' + (index + 1) + ' must be a mapping');
    }
    ['id', 'spider', 'action'].forEach(function (field) {
      if (!step[field]) throw new Error(slug + ': step #' + (index + 1) + ' missing ' + field);
    });
  }

  function accessMatchMode(access, slug) {
    var modes = new Set();
    Object.keys(access).forEach(function (permission) {
      if (!permissions.includes(permission)) {
        throw new Error(slug + ': unsupported access permission ' + permission);
      }
      var rule = asMapping(access[permission], slug + '.access.' + permission);
      modes.add(String(rule.match || 'all'));
      ['roles', 'teams'].forEach(function (subject) {
        if (rule[subject] !== undefined && !Array.isArray(rule[subject])) {
          throw new Error(slug + '.access.' + permission + '.' + subject + ' must be a list');
        }
      });
    });
    if (modes.size > 1) {
      throw new Error(slug + ': mixed access match modes cannot be preserved by the current editor');
    }
    return modes.size ? Array.from(modes)[0] : 'all';
  }

  function validatePayload(payload) {
    var existingComponents = new Set();
    document.querySelectorAll('[data-component-slug]').forEach(function (node) {
      if (node.dataset.componentSlug) existingComponents.add(node.dataset.componentSlug);
    });
    Object.keys(payload.components).forEach(function (slug) {
      if (!slug.trim()) throw new Error('component slug cannot be empty');
      asMapping(payload.components[slug], 'component ' + slug);
      existingComponents.add(slug);
    });

    Object.keys(payload.scenarios).forEach(function (slug) {
      if (!slugPattern.test(slug)) {
        throw new Error('invalid scenario slug: ' + slug);
      }
      var definition = asMapping(payload.scenarios[slug], 'scenario ' + slug);
      if (!definition.label) throw new Error(slug + ': missing required field label');
      if (!definition.component) throw new Error(slug + ': missing required field component');
      if (!existingComponents.has(String(definition.component))) {
        throw new Error(slug + ': unknown component ' + definition.component);
      }
      if (!Array.isArray(definition.steps) || !definition.steps.length) {
        throw new Error(slug + ': steps must be a non-empty list');
      }
      var ids = new Set();
      definition.steps.forEach(function (step, index) {
        validateStep(step, slug, index);
        if (ids.has(step.id)) throw new Error(slug + ': duplicate step id ' + step.id);
        ids.add(step.id);
      });
      var access = asMapping(definition.access, slug + '.access');
      accessMatchMode(access, slug);
    });
  }

  function existingScenarioSlugs() {
    return new Set(Array.from(document.querySelectorAll('[data-scenario-slug]')).map(function (row) {
      return row.dataset.scenarioSlug;
    }).filter(Boolean));
  }

  function existingComponentSlugs() {
    return new Set(Array.from(document.querySelectorAll('[data-component-slug]')).map(function (node) {
      return node.dataset.componentSlug;
    }).filter(Boolean));
  }

  async function postForm(url, body, label) {
    var response = await fetch(url, {
      method: 'POST',
      body: body,
      credentials: 'same-origin',
      redirect: 'follow'
    });
    if (!response.ok) {
      var detail = (await response.text()).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
      throw new Error(label + ' failed: HTTP ' + response.status + (detail ? ' · ' + detail.slice(0, 280) : ''));
    }
  }

  function componentForm(slug, spec, index) {
    var body = new URLSearchParams();
    body.set('slug', slug);
    body.set('label', String(spec.label || slug));
    body.set('icon', String(spec.icon || 'ti-box'));
    body.set('sort_order', String(spec.sort_order === undefined ? index : spec.sort_order));
    return body;
  }

  function scenarioForm(slug, source, exists) {
    var definition = Object.assign({}, source);
    var access = asMapping(definition.access, slug + '.access');
    delete definition.access;

    var body = new URLSearchParams();
    body.set('slug', slug);
    body.set('original_slug', exists ? slug : '');
    body.set('definition', window.jsyaml.dump(definition, {
      noRefs: true,
      lineWidth: -1,
      sortKeys: false
    }));
    body.set('comment', 'Imported from YAML');
    body.set('match_mode', accessMatchMode(access, slug));

    permissions.forEach(function (permission) {
      var rule = access[permission];
      if (!rule) return;
      (rule.roles || []).forEach(function (role) {
        body.append(permission + '_roles', String(role));
      });
      (rule.teams || []).forEach(function (team) {
        body.append(permission + '_teams', String(team));
      });
    });
    return body;
  }

  async function applyImport(payload, mode) {
    var components = Object.entries(payload.components);
    var scenarios = Object.entries(payload.scenarios);
    var knownComponents = existingComponentSlugs();
    var knownScenarios = existingScenarioSlugs();
    var result = {
      componentsCreated: 0,
      componentsUpdated: 0,
      componentsSkipped: 0,
      scenariosCreated: 0,
      scenariosUpdated: 0,
      scenariosSkipped: 0
    };

    for (var i = 0; i < components.length; i += 1) {
      var componentSlug = components[i][0];
      var componentSpec = components[i][1] || {};
      var componentExists = knownComponents.has(componentSlug);
      if (componentExists && mode === 'add') {
        result.componentsSkipped += 1;
        continue;
      }
      setStatus('Importing component ' + componentSlug + '…', 'working');
      await postForm('/admin/components', componentForm(componentSlug, componentSpec, i), 'component ' + componentSlug);
      if (componentExists) result.componentsUpdated += 1;
      else result.componentsCreated += 1;
      knownComponents.add(componentSlug);
    }

    for (var j = 0; j < scenarios.length; j += 1) {
      var scenarioSlug = scenarios[j][0];
      var scenarioSpec = scenarios[j][1];
      var scenarioExists = knownScenarios.has(scenarioSlug);
      if (scenarioExists && mode === 'add') {
        result.scenariosSkipped += 1;
        continue;
      }
      setStatus('Importing scenario ' + scenarioSlug + '…', 'working');
      await postForm('/admin/scenarios/save', scenarioForm(scenarioSlug, scenarioSpec, scenarioExists), 'scenario ' + scenarioSlug);
      if (scenarioExists) result.scenariosUpdated += 1;
      else result.scenariosCreated += 1;
      knownScenarios.add(scenarioSlug);
    }
    return result;
  }

  function resultUrl(result) {
    var query = new URLSearchParams({
      import_created: String(result.scenariosCreated),
      import_updated: String(result.scenariosUpdated),
      import_skipped: String(result.scenariosSkipped),
      import_components: String(result.componentsCreated + result.componentsUpdated)
    });
    return '/admin/scenarios?' + query.toString();
  }

  openButton.addEventListener('click', function () {
    parsedPayload = null;
    form.reset();
    setStatus('Choose an Arachne YAML export or compatible scenario bundle.');
    submit.disabled = true;
    dialog.showModal();
  });

  fileInput.addEventListener('change', async function () {
    parsedPayload = null;
    submit.disabled = true;
    var file = fileInput.files && fileInput.files[0];
    if (!file) {
      setStatus('Choose a YAML file.');
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setStatus('YAML file is larger than 5 MiB.', 'error');
      return;
    }
    try {
      var text = await file.text();
      var payload = parsePayload(text);
      validatePayload(payload);
      parsedPayload = payload;
      setStatus(
        Object.keys(payload.components).length + ' component(s) · ' +
        Object.keys(payload.scenarios).length + ' scenario(s) ready to import.',
        'ready'
      );
      submit.disabled = false;
    } catch (error) {
      setStatus(error.message || String(error), 'error');
    }
  });

  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    if (!parsedPayload) return;
    submit.disabled = true;
    fileInput.disabled = true;
    modeInput.disabled = true;
    try {
      var result = await applyImport(parsedPayload, modeInput.value);
      setStatus('Import complete. Reloading…', 'ready');
      window.location.assign(resultUrl(result));
    } catch (error) {
      setStatus(error.message || String(error), 'error');
      submit.disabled = false;
      fileInput.disabled = false;
      modeInput.disabled = false;
    }
  });
})();
