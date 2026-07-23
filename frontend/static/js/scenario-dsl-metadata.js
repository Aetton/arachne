(function () {
  var textarea = document.getElementById('scenario-definition');
  if (!textarea || !window.CodeMirror) return;

  var wrapper = textarea.nextElementSibling;
  var editor = wrapper && wrapper.CodeMirror;
  if (!editor) return;

  var form = document.getElementById('scenario-form');
  var saveButton = document.getElementById('scenario-save-button');
  var metadata = null;
  var spidersByName = {};

  function submitEditor() {
    editor.save();
    if (form && form.requestSubmit) form.requestSubmit(saveButton || undefined);
    else if (form) form.submit();
  }

  function applyEditorTheme() {
    var theme = document.documentElement.getAttribute('data-theme');
    var editorTheme = 'default';
    if (theme === 'dracula') editorTheme = 'dracula';
    else if (theme === 'nord') editorTheme = 'nord';
    editor.setOption('theme', editorTheme);
  }

  applyEditorTheme();
  new MutationObserver(applyEditorTheme).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme']
  });

  document.addEventListener('keydown', function (event) {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== 's') return;
    event.preventDefault();
    event.stopPropagation();
    submitEditor();
  }, true);

  function currentSection(cm, lineNo) {
    for (var i = lineNo; i >= 0; i--) {
      var text = cm.getLine(i);
      if (/^steps:\s*$/.test(text)) return 'steps';
      if (/^params:\s*$/.test(text)) return 'params';
      if (/^triggers:\s*$/.test(text)) return 'triggers';
      if (/^\S/.test(text) && text.trim()) return 'root';
    }
    return 'root';
  }

  function currentSpider(cm, lineNo) {
    for (var i = lineNo; i >= 0; i--) {
      var line = cm.getLine(i);
      var match = line.match(/^\s*spider:\s*([^\s#]+)/);
      if (match) return match[1].replace(/^[\'"]|[\'"]$/g, '');
      if (/^\s*-\s+id:\s*/.test(line) && i !== lineNo) break;
      if (/^\S/.test(line) && !/^steps:\s*$/.test(line)) break;
    }
    return null;
  }

  function completionItems(values, detail) {
    return values.map(function (value) {
      if (typeof value === 'string') return {text: value, displayText: value};
      return {
        text: value.text,
        displayText: value.displayText || value.text,
        className: value.className || '',
        render: detail ? function (element) {
          element.textContent = value.displayText || value.text;
          if (value.detail) {
            var hint = document.createElement('span');
            hint.className = 'muted';
            hint.style.marginLeft = '.75rem';
            hint.textContent = value.detail;
            element.appendChild(hint);
          }
        } : undefined
      };
    });
  }

  function dynamicHint(cm) {
    var cursor = cm.getCursor();
    var line = cm.getLine(cursor.line);
    var token = cm.getTokenAt(cursor);
    var start = token.start;
    var end = cursor.ch;
    var section = currentSection(cm, cursor.line);
    var values = [];

    if (/^\s*spider:\s*/.test(line)) {
      start = line.indexOf(':') + 1;
      while (line[start] === ' ') start++;
      values = metadata.spiders.map(function (spider) {
        return {text: spider.name, detail: spider.kind + ' · ' + spider.description};
      });
    } else if (/^\s*action:\s*/.test(line)) {
      start = line.indexOf(':') + 1;
      while (line[start] === ' ') start++;
      var spider = spidersByName[currentSpider(cm, cursor.line)];
      values = (spider ? spider.actions : ['run']).map(function (action) {
        return {text: action, detail: spider ? spider.name : ''};
      });
    } else if (section === 'steps' && /^\s+(?:with:\s*|[a-zA-Z0-9_-]*$)/.test(line)) {
      var stepSpider = spidersByName[currentSpider(cm, cursor.line)];
      if (stepSpider) {
        values = Object.keys(stepSpider.inputs).sort().map(function (name) {
          var input = stepSpider.inputs[name] || {};
          var suffix = input.default !== undefined ? String(input.default) : '';
          return {
            text: name + ': ' + suffix,
            displayText: name,
            detail: (input.required ? 'required' : 'optional') +
              (input.description ? ' · ' + input.description : '')
          };
        });
      }
    } else if (/^\s*type:\s*/.test(line) && section === 'params') {
      start = line.indexOf(':') + 1;
      while (line[start] === ' ') start++;
      values = metadata.param_types;
    } else if (/^\s*type:\s*/.test(line) && section === 'triggers') {
      start = line.indexOf(':') + 1;
      while (line[start] === ' ') start++;
      values = metadata.triggers;
    }

    if (!values.length) return null;

    var prefix = line.slice(start, end).trim().toLowerCase();
    values = values.filter(function (item) {
      var text = typeof item === 'string' ? item : item.text;
      return !prefix || text.toLowerCase().indexOf(prefix) === 0;
    });

    return {
      list: completionItems(values, true),
      from: CodeMirror.Pos(cursor.line, start),
      to: CodeMirror.Pos(cursor.line, end)
    };
  }

  function renderCatalog() {
    var reference = document.querySelector('.dsl-reference');
    if (!reference || document.getElementById('dsl-plugin-catalog')) return;

    var block = document.createElement('div');
    block.id = 'dsl-plugin-catalog';
    block.style.marginTop = '1rem';
    block.innerHTML = '<h3 class="text-sm font-semibold">Installed spiders</h3>';

    metadata.spiders.forEach(function (spider) {
      var row = document.createElement('div');
      row.className = 'surface-2 rounded p-2 mt-2 text-xs';
      var inputs = Object.keys(spider.inputs);
      row.innerHTML = '<div><code>' + spider.name + '</code> ' +
        '<span class="muted">' + spider.kind + '</span></div>' +
        '<div class="muted mt-1">actions: ' + spider.actions.join(', ') + '</div>' +
        (inputs.length ? '<div class="muted mt-1">with: ' + inputs.join(', ') + '</div>' : '');
      reference.appendChild(row);
    });
  }

  var extraKeys = Object.assign({}, editor.getOption('extraKeys') || {});
  extraKeys['Ctrl-S'] = submitEditor;
  extraKeys['Cmd-S'] = submitEditor;
  editor.setOption('extraKeys', extraKeys);

  fetch('/api/admin/scenario-dsl', {credentials: 'same-origin'})
    .then(function (response) {
      if (!response.ok) throw new Error('DSL metadata request failed: ' + response.status);
      return response.json();
    })
    .then(function (payload) {
      metadata = payload;
      payload.spiders.forEach(function (spider) { spidersByName[spider.name] = spider; });

      var dynamicKeys = Object.assign({}, editor.getOption('extraKeys') || {});
      dynamicKeys['Ctrl-Space'] = function (cm) {
        cm.showHint({hint: dynamicHint, completeSingle: false});
      };
      editor.setOption('extraKeys', dynamicKeys);
      renderCatalog();
    })
    .catch(function (error) {
      console.warn('[scenario-editor] dynamic DSL metadata unavailable; using built-in hints', error);
    });
})();