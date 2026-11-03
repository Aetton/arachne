/* Presentation only: native form fields, save/restore endpoints and DSL remain authoritative. */
(function () {
  'use strict';
  var editor, model, lintTimer;
  function byId(id) { return document.getElementById(id); }
  function selectTab(name) {
    document.querySelectorAll('[data-editor-tab]').forEach(function (button) {
      var selected = button.dataset.editorTab === name;
      button.classList.toggle('active', selected);
      button.setAttribute('aria-selected', String(selected));
    });
    ['help', 'outline', 'acl'].forEach(function (key) {
      var panel = byId('editor-side-' + key);
      if (panel) panel.hidden = key !== name;
    });
  }
  function jump(line) {
    if (!editor) return;
    editor.setPosition({ lineNumber: line, column: 1 });
    editor.revealLineInCenter(line);
    editor.focus();
  }
  function outline() {
    var target = byId('editor-side-outline');
    if (!target || !model || !window.jsyaml) return;
    target.replaceChildren();
    var heading = document.createElement('h2');
    heading.textContent = 'Структура сценария';
    target.appendChild(heading);
    var data;
    try { data = window.jsyaml.load(model.getValue()) || {}; }
    catch (_) {
      var message = document.createElement('p');
      message.className = 'muted text-xs';
      message.textContent = 'Исправьте синтаксис YAML, чтобы увидеть структуру.';
      target.appendChild(message);
      return;
    }
    var steps = Array.isArray(data.steps) ? data.steps : [];
    var list = document.createElement('div'); list.className = 'dsl-outline-list';
    var lines = model.getValue().split('\n'), from = 0;
    steps.forEach(function (step, index) {
      if (!step || typeof step !== 'object') return;
      var line = lines.findIndex(function (text, i) {
        return i >= from && /^\s*-\s*id\s*:/.test(text) && text.indexOf(String(step.id)) !== -1;
      });
      if (line >= 0) from = line + 1;
      var button = document.createElement('button'); button.type = 'button';
      var number = document.createElement('span'); number.className = 'step-number'; number.textContent = String(index + 1).padStart(2, '0');
      var copy = document.createElement('span'); copy.textContent = step.id || 'Без id';
      var detail = document.createElement('small'); detail.textContent = (step.spider || 'Нет spider') + ' · ' + (step.action || 'Нет action');
      copy.appendChild(detail); button.append(number, copy);
      button.addEventListener('click', function () { jump(Math.max(1, line + 1)); });
      list.appendChild(button);
    });
    target.appendChild(list);
    var params = document.createElement('h3'); params.textContent = 'Параметры'; target.appendChild(params);
    (Array.isArray(data.params) ? data.params : []).forEach(function (param) {
      if (!param || typeof param !== 'object') return;
      var chip = document.createElement('span'); chip.className = 'dsl-param-chip';
      chip.textContent = (param.name || '?') + ' · ' + (param.type || '?'); target.appendChild(chip);
    });
  }
  function applyTheme() {
    if (!window.monaco || !editor) return;
    var light = document.documentElement.getAttribute('data-theme') === 'white';
    window.monaco.editor.defineTheme('arachne-readable', {
      base: light ? 'vs' : 'vs-dark', inherit: true,
      rules: [
        {token:'key', foreground:light?'6746A6':'9FD5E5'},
        {token:'string', foreground:light?'45734D':'D9C693'},
        {token:'comment', foreground:light?'8D829B':'8F879E'},
        {token:'keyword', foreground:light?'AC467B':'E8A2C5'},
        {token:'number', foreground:light?'7F54B8':'C5AAF1'},
        {token:'variable', foreground:light?'7F54B8':'C5AAF1'}
      ],
      colors: {
        'editor.background':light?'#FCFAFF':'#252532',
        'editor.foreground':light?'#382F43':'#E5E1EB',
        'editorLineNumber.foreground':light?'#AAA0B8':'#68657D',
        'editorLineNumber.activeForeground':light?'#684A96':'#C3A4F5',
        'editor.lineHighlightBackground':light?'#EDE8F580':'#32314180',
        'editor.selectionBackground':light?'#DCD0EF':'#514565',
        'editorCursor.foreground':light?'#8056B9':'#C3A4F5',
        'editorIndentGuide.background1':light?'#E5DEED':'#393746',
        'editorIndentGuide.activeBackground1':light?'#B9A5D2':'#706086',
        'editorSuggestWidget.background':light?'#FFFFFF':'#2D2C3C',
        'editorSuggestWidget.border':light?'#DFD8EB':'#48465D',
        'editorSuggestWidget.selectedBackground':light?'#EDE7F5':'#453C56',
        'editorHoverWidget.background':light?'#FFFFFF':'#2D2C3C',
        'editorHoverWidget.border':light?'#DFD8EB':'#48465D',
        'editorError.foreground':light?'#C04364':'#F3A2AE'
      }
    });
    window.monaco.editor.setTheme('arachne-readable');
  }
  function ready() {
    document.querySelectorAll('[data-editor-tab]').forEach(function (button) {
      button.addEventListener('click', function () { selectTab(button.dataset.editorTab); });
    });
    document.querySelectorAll('.acl-permission').forEach(function (section) {
      function count() {
        var n = section.querySelectorAll('input:checked').length;
        section.querySelector('.acl-selection-count').textContent = n ? 'Выбрано: ' + n : 'Не выбрано';
      }
      section.addEventListener('change', count); count();
    });
    var match = document.querySelector('.acl-editor select[name="match_mode"]');
    if (match) {
      function explain() { byId('acl-match-help').textContent = match.value === 'all' ? 'Нужны совпадения по роли и по команде.' : 'Достаточно совпадения по роли или по команде.'; }
      match.addEventListener('change', explain); explain();
    }
    var status = byId('scenario-editor-status');
    if (status) {
      var issues = document.createElement('div'); issues.id = 'scenario-diagnostic-list'; status.after(issues);
    }
    document.querySelectorAll('[data-editor-command]').forEach(function (button) {
      button.addEventListener('click', function () {
        if (!editor || !model) return;
        var command = button.dataset.editorCommand;
        if (command === 'find') editor.getAction('actions.find').run();
        if (command === 'wrap') {
          var on = button.getAttribute('aria-pressed') !== 'true';
          button.setAttribute('aria-pressed', String(on)); editor.updateOptions({ wordWrap: on ? 'on' : 'off' });
        }
        if (command === 'fullscreen') { document.querySelector('.scenario-editor-shell').classList.toggle('fullscreen'); editor.layout(); editor.focus(); }
        if (command === 'format') {
          try {
            var value = window.jsyaml.dump(window.jsyaml.load(model.getValue()), { indent: 2, lineWidth: -1, noRefs: true });
            editor.pushUndoStop(); editor.executeEdits('format-yaml', [{ range: model.getFullModelRange(), text: value }]); editor.pushUndoStop();
          } catch (_) { byId('scenario-save-status').textContent = 'Исправьте синтаксис YAML перед форматированием.'; byId('scenario-save-status').classList.add('is-error'); }
        }
      });
    });
  }
  window.addEventListener('arachne:scenarioEditorReady', function (event) {
    editor = event.detail.editor; model = event.detail.model;
    applyTheme();
    model.onDidChangeContent(function () { clearTimeout(lintTimer); lintTimer = setTimeout(outline, 220); });
    outline();
  });
  window.addEventListener('arachne:scenarioDiagnostics', function (event) {
    var target = byId('scenario-diagnostic-list'); if (!target) return;
    target.replaceChildren();
    (event.detail.errors || []).forEach(function (error) {
      var button = document.createElement('button'); button.type = 'button';
      button.textContent = 'Стр ' + (error.line + 1) + ' · ' + error.message;
      button.addEventListener('click', function () { jump(error.line + 1); }); target.appendChild(button);
    });
  });
  new MutationObserver(applyTheme).observe(document.documentElement, {attributes:true, attributeFilter:['data-theme']});
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      var shell = document.querySelector('.scenario-editor-shell.fullscreen');
      if (shell) { shell.classList.remove('fullscreen'); if (editor) editor.layout(); }
    }
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready);
  else ready();
})();
