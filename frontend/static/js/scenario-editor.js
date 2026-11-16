  (function () {
    var textarea = document.getElementById("scenario-definition");
    var container = document.getElementById("scenario-editor");
    var form = document.getElementById("scenario-form");
    var saveButton = document.getElementById("scenario-save-button");
    var saveStatus = document.getElementById("scenario-save-status");
    var editorStatus = document.getElementById("scenario-editor-status");
    if (!textarea || !container || !form || !window.require) return;

    var ROOT_KEYS = ["label: ", "component: ", "icon: \"ti-\"", "accent: ", "triggers:\n  - type: manual", "params:\n  - name: ", "steps:\n  - id: "];
    var STEP_KEYS = ["id: ", "spider: ", "action: ", "kind: ", "with: {}", "needs: []"];
    var PARAM_KEYS = ["name: ", "label: ", "type: ", "required: true", "default: ", "options: []", "group: basic", "group: advanced"];
    function dslMetadata() {
      return window.arachneDslCatalog ? window.arachneDslCatalog.get() : {};
    }
    var lintTimer = null;

    require.config({ paths: { vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs" } });
    require(["vs/editor/editor.main"], function () {
      monaco.languages.register({ id: "yaml" });
      monaco.languages.setMonarchTokensProvider("yaml", {
        tokenizer: {
          root: [
            [/^\s*#.*$/, "comment"],
            [/^(\s*(?:-\s+)?)([A-Za-z_][\w.-]*)(\s*:)/, ["", "key", ""]],
            [/"/, "string.quote", "@doubleQuotedString"],
            [/'/, "string.quote", "@singleQuotedString"],
            [/\$\{[^}]+\}/, "variable"],
            [/\b(?:true|false|null)\b(?=\s*(?:#.*)?$|[\],}])/i, "keyword"],
            [/~(?=\s*(?:#.*)?$|[\],}])/, "keyword"],
            [/-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?(?=\s*(?:#.*)?$|[\],}])/, "number"],
            [/#.*$/, "comment"],
            [/[{}\[\],&*!|>?%@]/, "tag"]
          ],

          doubleQuotedString: [
            [/\$\{[^}]+\}/, "variable"],
            [/\\(?:0|a|b|t|n|v|f|r|e| |"|\/|\\|N|_|L|P|x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8})/, "string.escape"],
            [/\\./, "invalid"],
            [/"/, "string.quote", "@pop"],
            [/[^\\$"]+/, "string"],
            [/./, "string"]
          ],

          singleQuotedString: [
            [/\$\{[^}]+\}/, "variable"],
            [/''/, "string.escape"],
            [/'/, "string.quote", "@pop"],
            [/[^'$]+/, "string"],
            [/./, "string"]
          ]
        }
      });

      monaco.editor.defineTheme("arachne-dracula", {
        base: "vs-dark",
        inherit: true,
        rules: [
          { token: "", foreground: "F1FA8C", background: "282A36" },
          { token: "comment", foreground: "6272A4", fontStyle: "italic" },
          { token: "string", foreground: "F1FA8C" },
          { token: "number", foreground: "BD93F9" },
          { token: "keyword", foreground: "FF79C6" },
          { token: "type", foreground: "8BE9FD", fontStyle: "italic" },
          { token: "tag", foreground: "FF79C6" },
          { token: "key", foreground: "8BE9FD" }
        ],
        colors: {
          "editor.background": "#282A36",
          "editor.foreground": "#F1FA8C",
          "editorLineNumber.foreground": "#6272A4",
          "editorLineNumber.activeForeground": "#F8F8F2",
          "editorCursor.foreground": "#F8F8F0",
          "editor.selectionBackground": "#44475A",
          "editor.inactiveSelectionBackground": "#44475A80",
          "editor.lineHighlightBackground": "#44475A33",
          "editorWhitespace.foreground": "#6272A480",
          "editorIndentGuide.background1": "#44475A",
          "editorIndentGuide.activeBackground1": "#6272A4",
          "editorBracketMatch.background": "#44475A",
          "editorBracketMatch.border": "#8BE9FD",
          "editorError.foreground": "#FF5555",
          "editorWidget.background": "#282A36",
          "editorWidget.border": "#6272A4",
          "editorSuggestWidget.background": "#282A36",
          "editorSuggestWidget.border": "#6272A4",
          "editorSuggestWidget.selectedBackground": "#44475A"
        }
      });

      var model = monaco.editor.createModel(textarea.value, "yaml");
      var editor = monaco.editor.create(container, {
        model: model,
        theme: "arachne-dracula",
        fontFamily: "Consolas, \"Liberation Mono\", monospace",
        fontSize: 13,
        fontWeight: "normal",
        fontLigatures: false,
        letterSpacing: 0,
        lineHeight: 22,
        lineNumbers: "on",
        minimap: { enabled: false },
        wordWrap: "off",
        tabSize: 2,
        insertSpaces: true,
        detectIndentation: false,
        automaticLayout: true,
        scrollBeyondLastLine: false,
        renderWhitespace: "selection",
        bracketPairColorization: { enabled: true },
        guides: { bracketPairs: true, indentation: true },
        suggest: { showWords: false },
        quickSuggestions: { other: true, comments: false, strings: true },
        padding: { top: 17, bottom: 20 }
      });

      window.dispatchEvent(new CustomEvent("arachne:scenarioEditorReady", { detail: { editor: editor, model: model } }));

      function currentSection(lineNumber) {
        for (var i = lineNumber; i >= 1; i--) {
          var text = model.getLineContent(i);
          if (/^steps:\s*$/.test(text)) return "steps";
          if (/^params:\s*$/.test(text)) return "params";
          if (/^triggers:\s*$/.test(text)) return "triggers";
          if (/^\S/.test(text) && text.trim()) return "root";
        }
        return "root";
      }

      monaco.languages.registerCompletionItemProvider("yaml", {
        provideCompletionItems: function (completionModel, position) {
          if (completionModel !== model) return { suggestions: [] };
          var metadata = dslMetadata();
          var spiders = (metadata.spiders || []).map(function (spider) { return spider.name; });
          var paramTypes = metadata.param_types || [];
          var triggers = metadata.triggers || [];
          var triggerKeys = triggers.map(function (name) { return 'type: ' + name; });
          var line = model.getLineContent(position.lineNumber);
          var section = currentSection(position.lineNumber);
          var list = section === "steps" ? STEP_KEYS.concat(spiders) :
            section === "params" ? PARAM_KEYS.concat(paramTypes) :
            section === "triggers" ? triggerKeys : ROOT_KEYS;
          var word = model.getWordUntilPosition(position);
          var startColumn = word.startColumn;

          if (/^\s*(?:-\s*)?spider:\s*/.test(line)) list = spiders;
          if (/^\s*(?:-\s*)?type:\s*/.test(line) && section === "params") list = paramTypes;
          if (/^\s*(?:-\s*)?type:\s*/.test(line) && section === "triggers") list = triggers;
          if (/^\s*(?:-\s*)?(spider|type):\s*/.test(line)) {
            startColumn = line.indexOf(":") + 2;
            while (line.charAt(startColumn - 1) === " ") startColumn++;
          }

          return {
            suggestions: list.map(function (value) {
              return {
                label: value.replace(/\n/g, " ↵ "),
                kind: monaco.languages.CompletionItemKind.Property,
                insertText: value,
                range: new monaco.Range(position.lineNumber, startColumn, position.lineNumber, position.column)
              };
            })
          };
        }
      });

      function addError(errors, message, line) {
        errors.push({ message: message, line: Math.max(0, Number(line) || 0) });
      }

      function lineForKey(key, fromLine) {
        var escaped = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        var rx = new RegExp("^\\s*(?:-\\s*)?" + escaped + "\\s*:");
        for (var i = Math.max(1, (fromLine || 0) + 1); i <= model.getLineCount(); i++) {
          if (rx.test(model.getLineContent(i))) return i - 1;
        }
        return fromLine || 0;
      }

      function lintDsl(doc) {
        var errors = [];
        if (!doc || typeof doc !== "object" || Array.isArray(doc)) {
          addError(errors, "Scenario definition must be a mapping.", 0);
          return errors;
        }
        ["label", "component", "steps"].forEach(function (field) {
          if (!(field in doc)) addError(errors, "Missing required field: " + field, 0);
        });
        if (!Array.isArray(doc.steps) || !doc.steps.length) {
          addError(errors, "steps must be a non-empty list.", lineForKey("steps", 0));
        }

        var stepIds = {};
        (Array.isArray(doc.steps) ? doc.steps : []).forEach(function (step, index) {
          var line = lineForKey("id", lineForKey("steps", 0) + index);
          if (!step || typeof step !== "object" || Array.isArray(step)) {
            addError(errors, "Each step must be a mapping.", line);
            return;
          }
          ["id", "spider", "action"].forEach(function (field) {
            if (!step[field]) addError(errors, "Step " + (index + 1) + " is missing: " + field, line);
          });
          if (step.id) {
            if (stepIds[step.id] !== undefined) addError(errors, "Duplicate step id: " + step.id, line);
            stepIds[step.id] = index;
          }
          if (step.needs && !Array.isArray(step.needs)) addError(errors, "needs must be a list.", line);
          if (step.with && (typeof step.with !== "object" || Array.isArray(step.with))) {
            addError(errors, "with must be a mapping.", line);
          }
        });

        var params = {};
        (Array.isArray(doc.params) ? doc.params : []).forEach(function (param, index) {
          var line = lineForKey("name", lineForKey("params", 0) + index);
          if (!param || typeof param !== "object" || Array.isArray(param)) {
            addError(errors, "Each param must be a mapping.", line);
            return;
          }
          if (param.group !== undefined && ["basic", "advanced"].indexOf(param.group) < 0) addError(errors, "Param group must be basic or advanced.", line);
          if (!param.name) addError(errors, "Param " + (index + 1) + " is missing: name", line);
          if (!param.type) addError(errors, "Param " + (index + 1) + " is missing: type", line);
          if (param.type && (dslMetadata().param_types || []).length && dslMetadata().param_types.indexOf(param.type) < 0) addError(errors, "Unknown param type: " + param.type, line);
          if (param.type === "choice" && (!Array.isArray(param.options) || !param.options.length)) {
            addError(errors, "Choice param requires non-empty options.", line);
          }
          if (param.name) params[param.name] = true;
        });

        var refRx = /\$\{([^}]+)\}/g;
        var match;
        while ((match = refRx.exec(model.getValue()))) {
          var ref = match[1];
          var line = model.getPositionAt(match.index).lineNumber - 1;
          if (ref.indexOf("params.") === 0) {
            if (!params[ref.slice(7).split(".")[0]]) addError(errors, "Unknown parameter reference: " + ref, line);
          } else if (stepIds[ref.split(".")[0]] === undefined) {
            addError(errors, "Unknown step reference: " + ref, line);
          }
        }
        return errors;
      }

      function validateEditor() {
        var errors = [];
        try {
          errors = lintDsl(window.jsyaml.load(model.getValue()));
        } catch (error) {
          addError(errors, error.reason || error.message || "Invalid YAML.", error && error.mark ? error.mark.line : 0);
        }
        monaco.editor.setModelMarkers(model, "arachne-dsl", errors.map(function (error) {
          var lineNumber = Math.min(error.line + 1, model.getLineCount());
          return {
            severity: monaco.MarkerSeverity.Error,
            message: error.message,
            startLineNumber: lineNumber,
            startColumn: 1,
            endLineNumber: lineNumber,
            endColumn: model.getLineMaxColumn(lineNumber)
          };
        }));
        editorStatus.classList.remove("is-ok", "is-error");
        editorStatus.classList.add(errors.length ? "is-error" : "is-ok");
        editorStatus.querySelector("span:last-child").textContent = errors.length ?
          errors.length + " DSL error" + (errors.length === 1 ? "" : "s") + ": " + errors[0].message :
          "Valid YAML and Arachne DSL · " + model.getLineCount() + " lines";
        window.dispatchEvent(new CustomEvent("arachne:scenarioDiagnostics", { detail: { errors: errors } }));
        return errors;
      }

      function syncTextarea() {
        textarea.value = model.getValue();
      }

      function submitEditor() {
        syncTextarea();
        if (form.requestSubmit) form.requestSubmit(saveButton);
        else form.submit();
      }

      editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, submitEditor);
      model.onDidChangeContent(function () {
        syncTextarea();
        window.clearTimeout(lintTimer);
        lintTimer = window.setTimeout(validateEditor, 250);
      });
      validateEditor();

      form.addEventListener("submit", async function (event) {
        syncTextarea();
        var submitter = event.submitter;
        var targetAction = submitter && submitter.formAction ? submitter.formAction : form.action;
        if (!targetAction.endsWith("/admin/scenarios/save")) return;
        event.preventDefault();
        saveStatus.classList.remove("is-error");
        saveStatus.textContent = "";

        var errors = validateEditor();
        if (errors.length) {
          saveStatus.textContent = "Fix DSL errors before publishing.\n" + errors.map(function (error) {
            return "Line " + (error.line + 1) + ": " + error.message;
          }).join("\n");
          saveStatus.classList.add("is-error");
          editor.setPosition({ lineNumber: errors[0].line + 1, column: 1 });
          editor.revealLineInCenter(errors[0].line + 1);
          editor.focus();
          return;
        }

        saveButton.disabled = true;
        saveButton.style.filter = "grayscale(.35)";
        try {
          var response = await fetch(form.action, {
            method: "POST",
            body: new FormData(form),
            credentials: "same-origin"
          });
          if (!response.ok) {
            saveStatus.textContent = await response.text();
            saveStatus.classList.add("is-error");
            return;
          }
          var slug = String(new FormData(form).get("slug") || "").trim();
          window.location.assign("/admin/scenarios/" + encodeURIComponent(slug) + "/edit");
        } catch (error) {
          saveStatus.textContent = error && error.message ? error.message : String(error);
          saveStatus.classList.add("is-error");
        } finally {
          saveButton.disabled = false;
          saveButton.style.filter = "";
        }
      });
    });
  })();
