(() => {
  const dialog = document.getElementById("scenario-import-dialog");
  const open = document.getElementById("scenario-import-open");
  const form = document.getElementById("scenario-import-form");
  const input = document.getElementById("scenario-import-file");
  const mode = document.getElementById("scenario-import-mode");
  const status = document.getElementById("scenario-import-status");
  const submit = document.getElementById("scenario-import-submit");
  if (!dialog || !open || !form || !input || !mode || !status || !submit)
    return;
  let text = null,
    generation = 0,
    busy = false;
  function message(value, kind = "") {
    status.textContent = value;
    status.className = "scenario-import-status" + (kind ? " is-" + kind : "");
  }
  function controls(disabled) {
    input.disabled = mode.disabled = disabled;
    submit.disabled = disabled || text === null;
    dialog.querySelectorAll('button[type="button"]').forEach((b) => {
      b.disabled = disabled;
    });
  }
  dialog.addEventListener("cancel", (event) => {
    if (busy) event.preventDefault();
  });
  open.addEventListener("click", () => {
    if (busy) return;
    generation++;
    text = null;
    form.reset();
    controls(false);
    message(
      "Выберите YAML. Сервер проверит весь пакет перед завершением импорта.",
    );
    dialog.showModal();
  });
  input.addEventListener("change", async () => {
    const current = ++generation;
    text = null;
    submit.disabled = true;
    const file = input.files?.[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      message("Файл больше 5 MiB.", "error");
      return;
    }
    try {
      const value = await file.text();
      if (current !== generation) return;
      text = value;
      submit.disabled = false;
      message(`${file.name}: готов к проверке и импорту.`, "ready");
    } catch (error) {
      if (current === generation) message(error.message, "error");
    }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || text === null) return;
    busy = true;
    controls(true);
    message("Проверяю и импортирую пакет…", "working");
    try {
      const response = await fetch(
        "/admin/scenarios/import?mode=" + encodeURIComponent(mode.value),
        {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/yaml" },
          body: text,
        },
      );
      if (response.redirected)
        throw new Error("Сессия закончилась. Войдите заново.");
      const result = await response.json();
      if (!response.ok)
        throw new Error(
          Array.isArray(result.detail)
            ? result.detail.map((e) => e.msg).join("; ")
            : result.detail || "Ошибка импорта",
        );
      const query = new URLSearchParams({
        import_created: result.scenariosCreated,
        import_updated: result.scenariosUpdated,
        import_skipped: result.scenariosSkipped,
        import_components: result.componentsCreated + result.componentsUpdated,
      });
      message("Пакет сохранён. Обновляю страницу…", "ready");
      window.location.assign("/admin/scenarios?" + query);
    } catch (error) {
      message(
        error.message +
          " Если связь прервалась, проверьте результат перед повторным импортом.",
        "error",
      );
      busy = false;
      controls(false);
    }
  });
})();
