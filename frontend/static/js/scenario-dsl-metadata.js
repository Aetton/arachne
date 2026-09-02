(function () {
  var FALLBACK_METADATA = {
    docs_url: '/wiki/ru/reference/scenario-syntax',
    families: ['weave', 'brood', 'command'],
    family_help: {
      weave: 'Создание build artifacts.',
      brood: 'Создание вычислительных окружений.',
      command: 'Действия над существующими окружениями.'
    },
    spiders: [
      {
        name: 'ansible-local', family: 'command', actions: ['command'],
        action_help: {command: 'Выполнить ansible-playbook над target.'},
        inputs: {
          playbook: {description: 'Playbook из настроенного Git repository.'},
          playbook_ref: {description: 'Необязательный override Git ref для playbook repository.'},
          target: {description: 'Brood artifact или явный hostname/IP.'}
        },
        description: 'Run ansible-playbook on a target or locally.',
        docs_url: '/wiki/ru/reference/spiders#ansible-local',
        example: '- id: deploy\n  spider: ansible-local\n  action: command\n  with:\n    target: "${stand.artifact}"\n    playbook: install.yml\n    playbook_ref: main'
      },
      {
        name: 'forgejo', family: 'weave', actions: ['weave'],
        action_help: {weave: 'Запустить Forgejo Actions workflow.'},
        inputs: {repo: {description: 'Имя репозитория.'}, workflow: {description: 'Файл workflow.'}, ref: {description: 'Git ref/ветка.'}},
        description: 'Dispatch a Forgejo Actions workflow.',
        docs_url: '/wiki/ru/reference/spiders#forgejo',
        example: '- id: build\n  spider: forgejo\n  action: weave\n  with:\n    repo: backend\n    workflow: build.yaml'
      },
      {
        name: 'tofu-proxmox', family: 'brood', actions: ['brood', 'destroy'],
        action_help: {brood: 'Создать стенд.', destroy: 'Уничтожить стенд.'},
        inputs: {name: {description: 'Имя стенда.'}, os: {description: 'Семейство ОС.'}, image: {description: 'Golden Image profile.'}, lifetime: {description: 'TTL: 30m, 2h, 1d.'}, resources: {description: 'cpu, memory_gb, disk_gb.'}},
        description: 'Create or destroy a Proxmox stand through OpenTofu.',
        docs_url: '/wiki/ru/operations/proxmox-opentofu',
        example: '- id: stand\n  spider: tofu-proxmox\n  action: brood\n  with:\n    name: test-001\n    os: redos8\n    lifetime: 30m'
      }
    ]
  };

  var metadataCache = FALLBACK_METADATA;

  function makeText(tag, text, className) {
    var node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function spiderByName(name) {
    return (metadataCache.spiders || []).find(function (item) { return item.name === name; });
  }

  function currentSpider(model, lineNumber) {
    for (var i = lineNumber; i >= 1; i--) {
      var text = model.getLineContent(i);
      var match = text.match(/^\s*spider:\s*["']?([^\s"']+)/);
      if (match) return match[1];
      if (/^\s*-\s+id:\s*/.test(text) && i !== lineNumber) break;
    }
    return '';
  }

  function markdown(value) {
    return {value: value};
  }

  function registerHoverProvider() {
    if (!window.monaco || window.__arachneDslHoverRegistered) return;
    window.__arachneDslHoverRegistered = true;

    monaco.languages.registerHoverProvider('yaml', {
      provideHover: function (model, position) {
        if (!model || model.getLanguageId() !== 'yaml') return null;
        var line = model.getLineContent(position.lineNumber);
        var wordInfo = model.getWordAtPosition(position);
        var word = wordInfo ? wordInfo.word : '';
        var spiderName = currentSpider(model, position.lineNumber);
        var spider = spiderByName(spiderName);
        var contents = [];

        var spiderMatch = line.match(/^\s*spider:\s*["']?([^\s"']+)/);
        if (spiderMatch) {
          var selected = spiderByName(spiderMatch[1]);
          if (selected) {
            contents.push(markdown('**' + selected.name + '** · `' + selected.family + '`'));
            contents.push(markdown(selected.description || 'Installed Arachne spider.'));
            if (selected.example) contents.push(markdown('```yaml\n' + selected.example + '\n```'));
            if (selected.docs_url) contents.push(markdown('[Открыть документацию](' + selected.docs_url + ')'));
            return {contents: contents};
          }
        }

        var actionMatch = line.match(/^\s*action:\s*["']?([^\s"']+)/);
        if (actionMatch && spider) {
          var action = actionMatch[1];
          var help = (spider.action_help || {})[action];
          contents.push(markdown('**action: `' + action + '`**'));
          contents.push(markdown(help || 'Действие spider `' + spider.name + '`.'));
          contents.push(markdown('Семейство: `' + spider.family + '`.'));
          if (spider.docs_url) contents.push(markdown('[Документация spider](' + spider.docs_url + ')'));
          return {contents: contents};
        }

        var keyMatch = line.match(/^\s{4,}([A-Za-z_][\w.-]*)\s*:/);
        if (keyMatch && spider && spider.inputs && spider.inputs[keyMatch[1]]) {
          var input = spider.inputs[keyMatch[1]];
          contents.push(markdown('**with.' + keyMatch[1] + '**'));
          contents.push(markdown(input.description || 'Параметр spider `' + spider.name + '`.'));
          if (input.required) contents.push(markdown('**Обязательный параметр.**'));
          if (input.default !== undefined) contents.push(markdown('По умолчанию: `' + input.default + '`.'));
          if (input.options && input.options.length) contents.push(markdown('Варианты: `' + input.options.join('`, `') + '`.'));
          return {contents: contents};
        }

        var familyMatch = line.match(/^\s*family:\s*["']?([^\s"']+)/);
        if (familyMatch) {
          var family = familyMatch[1];
          contents.push(markdown('**family: `' + family + '`**'));
          contents.push(markdown((metadataCache.family_help || {})[family] || 'Семейство spider.'));
          contents.push(markdown('Обычно `family` указывать не нужно: Arachne получает его из registry.'));
          return {contents: contents};
        }

        if (word === 'with') {
          return {contents: [
            markdown('**with**'),
            markdown('Параметры конкретного spider. Наведи курсор на любой ключ внутри `with`, чтобы увидеть его описание, default и допустимые значения.')
          ]};
        }

        if (line.indexOf('${') !== -1) {
          return {contents: [
            markdown('**Scenario reference**'),
            markdown('`${params.name}` берёт input сценария. `${step_id.field}` берёт поле результата предыдущего шага. `${step_id.artifact}` передаёт structured artifact целиком.'),
            markdown('[Синтаксис ссылок](' + (metadataCache.docs_url || '/wiki/ru/reference/scenario-syntax') + ')')
          ]};
        }

        if (word === 'kind') {
          return {contents: [
            markdown('**`kind` устарел.**'),
            markdown('Это legacy wire-routing поле `build/provision`. В новом DSL используйте `family`, а обычно не указывайте и его.')
          ]};
        }

        return null;
      }
    });
  }

  function copyExample(button, text) {
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(text).then(function () {
      var old = button.textContent;
      button.textContent = 'Copied';
      setTimeout(function () { button.textContent = old; }, 1200);
    });
  }

  function scenarioModel() {
    if (!window.monaco || !monaco.editor || !monaco.editor.getModels) return null;
    var models = monaco.editor.getModels();
    for (var i = 0; i < models.length; i++) {
      if (models[i].getLanguageId && models[i].getLanguageId() === 'yaml') return models[i];
    }
    return models.length ? models[0] : null;
  }

  function ansibleSteps(model) {
    if (!model || !window.jsyaml) return [];
    try {
      var doc = window.jsyaml.load(model.getValue()) || {};
      return (Array.isArray(doc.steps) ? doc.steps : []).filter(function (step) {
        return step && step.spider === 'ansible-local' && step.id;
      }).map(function (step) {
        return {
          id: String(step.id),
          playbook: step.with && step.with.playbook ? String(step.with.playbook) : '',
          ref: step.with && step.with.playbook_ref ? String(step.with.playbook_ref) : ''
        };
      });
    } catch (error) {
      return [];
    }
  }

  function yamlScalar(value) {
    return JSON.stringify(String(value));
  }

  function leadingSpaces(text) {
    var match = String(text || '').match(/^(\s*)/);
    return match ? match[1].length : 0;
  }

  function stepRange(lines, stepId) {
    for (var i = 0; i < lines.length; i++) {
      var match = lines[i].match(/^(\s*)-\s+id:\s*["']?([^"'#\s]+)["']?\s*(?:#.*)?$/);
      if (!match || match[2] !== stepId) continue;
      var indent = match[1].length;
      var end = lines.length;
      for (var j = i + 1; j < lines.length; j++) {
        var next = lines[j];
        if (!next.trim()) continue;
        if (leadingSpaces(next) < indent) {
          end = j;
          break;
        }
        if (leadingSpaces(next) === indent && /^\s*-\s+id:\s*/.test(next)) {
          end = j;
          break;
        }
      }
      return {start: i, end: end, indent: indent};
    }
    return null;
  }

  function applyPlaybookToStep(model, stepId, playbook, ref) {
    if (!model) throw new Error('Scenario YAML model is not ready yet.');
    var lines = model.getValue().split('\n');
    var range = stepRange(lines, stepId);
    if (!range) throw new Error('Cannot find step ' + stepId + ' in YAML.');

    var keyIndent = range.indent + 2;
    var childIndent = keyIndent + 2;
    var withIndex = -1;
    for (var i = range.start + 1; i < range.end; i++) {
      if (leadingSpaces(lines[i]) === keyIndent && /^\s*with:\s*(?:\{\s*\})?\s*(?:#.*)?$/.test(lines[i])) {
        withIndex = i;
        break;
      }
    }

    if (withIndex < 0) {
      var insertAt = range.end;
      for (var n = range.start + 1; n < range.end; n++) {
        if (leadingSpaces(lines[n]) === keyIndent && /^\s*needs:\s*/.test(lines[n])) {
          insertAt = n;
          break;
        }
      }
      lines.splice(
        insertAt,
        0,
        ' '.repeat(keyIndent) + 'with:',
        ' '.repeat(childIndent) + 'playbook: ' + yamlScalar(playbook),
        ' '.repeat(childIndent) + 'playbook_ref: ' + yamlScalar(ref)
      );
      model.setValue(lines.join('\n'));
      return;
    }

    if (/^\s*with:\s*\{\s*\}\s*(?:#.*)?$/.test(lines[withIndex])) {
      lines[withIndex] = ' '.repeat(keyIndent) + 'with:';
      lines.splice(
        withIndex + 1,
        0,
        ' '.repeat(childIndent) + 'playbook: ' + yamlScalar(playbook),
        ' '.repeat(childIndent) + 'playbook_ref: ' + yamlScalar(ref)
      );
      model.setValue(lines.join('\n'));
      return;
    }

    var blockEnd = range.end;
    for (var k = withIndex + 1; k < range.end; k++) {
      if (!lines[k].trim()) continue;
      if (leadingSpaces(lines[k]) <= keyIndent) {
        blockEnd = k;
        break;
      }
    }

    var foundPlaybook = false;
    var foundRef = false;
    for (var p = withIndex + 1; p < blockEnd; p++) {
      if (leadingSpaces(lines[p]) !== childIndent) continue;
      if (/^\s*playbook:\s*/.test(lines[p])) {
        lines[p] = ' '.repeat(childIndent) + 'playbook: ' + yamlScalar(playbook);
        foundPlaybook = true;
      } else if (/^\s*playbook_ref:\s*/.test(lines[p])) {
        lines[p] = ' '.repeat(childIndent) + 'playbook_ref: ' + yamlScalar(ref);
        foundRef = true;
      }
    }

    var additions = [];
    if (!foundPlaybook) additions.push(' '.repeat(childIndent) + 'playbook: ' + yamlScalar(playbook));
    if (!foundRef) additions.push(' '.repeat(childIndent) + 'playbook_ref: ' + yamlScalar(ref));
    if (additions.length) lines.splice.apply(lines, [blockEnd, 0].concat(additions));
    model.setValue(lines.join('\n'));
  }

  function requestJson(url) {
    return fetch(url, {credentials: 'same-origin', cache: 'no-store'}).then(function (response) {
      if (!response.ok) {
        return response.text().then(function (text) {
          throw new Error(text || ('Request failed: ' + response.status));
        });
      }
      return response.json();
    });
  }

  function makeField(labelText, control) {
    var field = document.createElement('label');
    field.className = 'block mt-2';
    field.appendChild(makeText('span', labelText, 'muted text-xs block mb-1'));
    field.appendChild(control);
    return field;
  }

  function renderPlaybookPicker(reference) {
    if (!reference || reference.querySelector('[data-playbook-picker]')) return;

    var wrap = document.createElement('div');
    wrap.dataset.playbookPicker = '1';
    wrap.className = 'surface-2 rounded p-3 mt-4 text-xs';

    var heading = document.createElement('div');
    heading.className = 'flex items-center justify-between gap-2';
    heading.appendChild(makeText('h3', 'Ansible playbook picker', 'font-semibold'));
    var manage = document.createElement('a');
    manage.href = '/admin/ansible';
    manage.className = 'link text-xs';
    manage.textContent = 'Repository settings ↗';
    heading.appendChild(manage);
    wrap.appendChild(heading);

    wrap.appendChild(makeText('div', 'Выбирает playbook из настроенного Git source и обновляет with.* у выбранного ansible-local step.', 'muted mt-2'));

    var stepSelect = document.createElement('select');
    stepSelect.dataset.playbookStep = '1';
    wrap.appendChild(makeField('Step', stepSelect));

    var refSelect = document.createElement('select');
    refSelect.dataset.playbookRef = '1';
    wrap.appendChild(makeField('Ref', refSelect));

    var filter = document.createElement('input');
    filter.type = 'search';
    filter.placeholder = 'filter playbooks…';
    filter.dataset.playbookFilter = '1';
    wrap.appendChild(makeField('Filter', filter));

    var playbookSelect = document.createElement('select');
    playbookSelect.size = 8;
    playbookSelect.style.minHeight = '11rem';
    playbookSelect.dataset.playbookPath = '1';
    wrap.appendChild(makeField('Playbook', playbookSelect));

    var resolved = makeText('div', 'Loading repository…', 'muted mt-2 mono');
    resolved.dataset.playbookResolved = '1';
    wrap.appendChild(resolved);

    var status = makeText('div', '', 'muted mt-2');
    status.dataset.playbookStatus = '1';
    wrap.appendChild(status);

    var apply = document.createElement('button');
    apply.type = 'button';
    apply.className = 'btn w-full mt-3';
    apply.innerHTML = '<i class="ti ti-arrow-back-up"></i> Apply to step';
    wrap.appendChild(apply);

    reference.insertBefore(wrap, reference.querySelector('h3.mt-4') || null);

    var allPlaybooks = [];
    var defaultRef = '';

    function refreshSteps() {
      var model = scenarioModel();
      var steps = ansibleSteps(model);
      var old = stepSelect.value;
      stepSelect.innerHTML = '';
      steps.forEach(function (step) {
        var option = document.createElement('option');
        option.value = step.id;
        option.textContent = step.id + (step.playbook ? ' · ' + step.playbook : '');
        option.dataset.ref = step.ref || '';
        stepSelect.appendChild(option);
      });
      if (old && steps.some(function (step) { return step.id === old; })) stepSelect.value = old;
      if (!steps.length) {
        var empty = document.createElement('option');
        empty.value = '';
        empty.textContent = 'No ansible-local steps';
        stepSelect.appendChild(empty);
        apply.disabled = true;
      } else {
        apply.disabled = false;
      }
    }

    function renderPlaybooks() {
      var needle = filter.value.trim().toLowerCase();
      var old = playbookSelect.value;
      playbookSelect.innerHTML = '';
      allPlaybooks.filter(function (path) {
        return !needle || path.toLowerCase().indexOf(needle) !== -1;
      }).forEach(function (path) {
        var option = document.createElement('option');
        option.value = path;
        option.textContent = path;
        playbookSelect.appendChild(option);
      });
      if (old && allPlaybooks.indexOf(old) !== -1) playbookSelect.value = old;
    }

    function loadPlaybooks(ref) {
      if (!ref) return;
      status.textContent = 'Loading playbooks…';
      requestJson('/api/admin/ansible/playbooks?ref=' + encodeURIComponent(ref))
        .then(function (data) {
          allPlaybooks = data.playbooks || [];
          resolved.textContent = (data.repo || '') + ' @ ' + (data.ref || ref) + ' · ' + String(data.sha || '').slice(0, 12);
          status.textContent = allPlaybooks.length + ' playbook' + (allPlaybooks.length === 1 ? '' : 's');
          renderPlaybooks();
        })
        .catch(function (error) {
          allPlaybooks = [];
          renderPlaybooks();
          resolved.textContent = 'Repository unavailable';
          status.textContent = error.message || String(error);
        });
    }

    requestJson('/api/admin/ansible/refs')
      .then(function (data) {
        defaultRef = data.default_ref || '';
        refSelect.innerHTML = '';
        (data.refs || []).forEach(function (ref) {
          var option = document.createElement('option');
          option.value = ref;
          option.textContent = ref + (ref === defaultRef ? ' · default' : '');
          refSelect.appendChild(option);
        });
        if (defaultRef) refSelect.value = defaultRef;
        loadPlaybooks(refSelect.value);
      })
      .catch(function (error) {
        refSelect.innerHTML = '';
        var option = document.createElement('option');
        option.value = '';
        option.textContent = 'Repository unavailable';
        refSelect.appendChild(option);
        resolved.textContent = 'Configure repository in Control → Ansible';
        status.textContent = error.message || String(error);
        apply.disabled = true;
      });

    refreshSteps();
    var model = scenarioModel();
    if (model && model.onDidChangeContent) {
      var timer = null;
      model.onDidChangeContent(function () {
        window.clearTimeout(timer);
        timer = window.setTimeout(refreshSteps, 150);
      });
    } else {
      window.setTimeout(refreshSteps, 800);
    }

    stepSelect.addEventListener('change', function () {
      var selected = stepSelect.options[stepSelect.selectedIndex];
      var stepRef = selected && selected.dataset ? selected.dataset.ref : '';
      if (stepRef && Array.prototype.some.call(refSelect.options, function (opt) { return opt.value === stepRef; })) {
        refSelect.value = stepRef;
        loadPlaybooks(stepRef);
      }
    });
    refSelect.addEventListener('change', function () { loadPlaybooks(refSelect.value); });
    filter.addEventListener('input', renderPlaybooks);
    apply.addEventListener('click', function () {
      var stepId = stepSelect.value;
      var playbook = playbookSelect.value;
      var ref = refSelect.value || defaultRef;
      if (!stepId || !playbook || !ref) {
        status.textContent = 'Choose step, ref and playbook first.';
        return;
      }
      try {
        applyPlaybookToStep(scenarioModel(), stepId, playbook, ref);
        status.textContent = 'Applied ' + playbook + ' @ ' + ref + ' to ' + stepId + '.';
        refreshSteps();
      } catch (error) {
        status.textContent = error.message || String(error);
      }
    });
  }

  function renderCatalog(metadata) {
    metadataCache = metadata || FALLBACK_METADATA;
    registerHoverProvider();

    var reference = document.querySelector('.dsl-reference');
    if (!reference) return;
    reference.innerHTML = '';

    var heading = document.createElement('div');
    heading.className = 'flex items-center justify-between gap-2';
    heading.appendChild(makeText('h2', 'DSL helper', 'font-semibold'));
    var docs = document.createElement('a');
    docs.className = 'link text-xs';
    docs.href = metadataCache.docs_url || '/wiki/ru/reference/scenario-syntax';
    docs.target = '_blank';
    docs.rel = 'noopener';
    docs.textContent = 'Полная документация ↗';
    heading.appendChild(docs);
    reference.appendChild(heading);

    var basics = document.createElement('div');
    basics.className = 'surface-2 rounded p-2 mt-3 text-xs';
    basics.appendChild(makeText('div', 'Шаг: id · spider · action · with · needs', 'muted'));
    basics.appendChild(makeText('div', 'Семейства: weave · brood · command', 'muted mt-1'));
    basics.appendChild(makeText('div', 'Hover по action / with.* / ${…} покажет справку.', 'muted mt-1'));
    reference.appendChild(basics);

    renderPlaybookPicker(reference);

    var title = makeText('h3', 'Installed spiders', 'text-sm font-semibold mt-4');
    reference.appendChild(title);

    (metadataCache.spiders || []).forEach(function (spider) {
      var row = document.createElement('details');
      row.className = 'surface-2 rounded p-2 mt-2 text-xs';

      var summary = document.createElement('summary');
      summary.style.cursor = 'pointer';
      summary.appendChild(makeText('code', spider.name));
      summary.appendChild(document.createTextNode(' '));
      summary.appendChild(makeText('span', spider.family || '', 'muted'));
      row.appendChild(summary);

      if (spider.description) row.appendChild(makeText('div', spider.description, 'muted mt-2'));

      var actions = document.createElement('div');
      actions.className = 'mt-2';
      actions.appendChild(makeText('strong', 'actions: '));
      (spider.actions || []).forEach(function (action, index) {
        if (index) actions.appendChild(document.createTextNode(', '));
        var code = makeText('code', action);
        code.title = (spider.action_help || {})[action] || '';
        actions.appendChild(code);
      });
      row.appendChild(actions);

      var inputs = Object.keys(spider.inputs || {});
      if (inputs.length) {
        var inputsBlock = document.createElement('div');
        inputsBlock.className = 'mt-2';
        inputsBlock.appendChild(makeText('strong', 'with: '));
        inputs.forEach(function (inputName, index) {
          if (index) inputsBlock.appendChild(document.createTextNode(', '));
          var code = makeText('code', inputName);
          code.title = (spider.inputs[inputName] || {}).description || '';
          inputsBlock.appendChild(code);
        });
        row.appendChild(inputsBlock);
      }

      if (spider.example) {
        var exampleTitle = makeText('div', 'Пример', 'font-semibold mt-3');
        row.appendChild(exampleTitle);
        var pre = document.createElement('pre');
        pre.className = 'surface rounded p-2 mt-1 overflow-x-auto';
        pre.style.whiteSpace = 'pre';
        pre.textContent = spider.example;
        row.appendChild(pre);
        var copy = document.createElement('button');
        copy.type = 'button';
        copy.className = 'btn-ghost text-xs mt-1';
        copy.textContent = 'Copy example';
        copy.addEventListener('click', function () { copyExample(copy, spider.example); });
        row.appendChild(copy);
      }

      if (spider.docs_url) {
        var link = document.createElement('a');
        link.className = 'link block mt-2';
        link.href = spider.docs_url;
        link.target = '_blank';
        link.rel = 'noopener';
        link.textContent = 'Документация →';
        row.appendChild(link);
      }

      reference.appendChild(row);
    });
  }

  function loadMetadata() {
    if (!document.querySelector('.dsl-reference')) return;
    renderCatalog(FALLBACK_METADATA);
    fetch('/api/admin/scenario-dsl', {credentials: 'same-origin', cache: 'no-store'})
      .then(function (response) {
        if (!response.ok) throw new Error('DSL metadata request failed: ' + response.status);
        return response.json();
      })
      .then(renderCatalog)
      .catch(function (error) {
        console.warn('[scenario-editor] live DSL metadata unavailable; fallback catalog retained', error);
      });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', loadMetadata);
  else loadMetadata();
})();
