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
        inputs: {playbook: {description: 'Путь к playbook.'}, target: {description: 'Brood artifact или явный hostname/IP.'}},
        description: 'Run ansible-playbook on a target or locally.',
        docs_url: '/wiki/ru/reference/spiders#ansible-local',
        example: '- id: deploy\n  spider: ansible-local\n  action: command\n  with:\n    target: "${stand.artifact}"\n    playbook: install.yml'
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
