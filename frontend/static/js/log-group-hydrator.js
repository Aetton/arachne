(() => {
  function streamOf(line) {
    if (line.classList.contains('stream-stderr')) return 'stderr';
    if (line.classList.contains('stream-system')) return 'system';
    return 'stdout';
  }

  function rebuild(viewer) {
    if (!window.ArachneLogViewer || viewer.dataset.groupsHydrated === 'true') return;
    if (viewer.closest('[data-live-run="true"]')) return;

    const rows = Array.from(viewer.querySelectorAll('.log-line')).map(line => ({
      text: line.dataset.raw || line.querySelector('.log-line-text')?.textContent || '',
      stream: streamOf(line),
    }));
    if (!rows.length) {
      viewer.dataset.groupsHydrated = 'true';
      return;
    }

    const lines = viewer.querySelector('.log-lines');
    if (!lines) return;
    lines.replaceChildren();
    viewer._arachneTarget = lines;
    viewer._arachneExplicitGroups = [];
    viewer._arachneImplicitGroup = null;
    viewer.dataset.nextLine = '1';

    rows.forEach(row => window.ArachneLogViewer.appendLine(viewer, row.text, row.stream));
    viewer.dataset.groupsHydrated = 'true';
  }

  function hydrate(root = document) {
    root.querySelectorAll?.('.log-viewer[data-rebuild-groups="true"]').forEach(rebuild);
  }

  document.addEventListener('DOMContentLoaded', () => hydrate());
  document.body.addEventListener('htmx:afterSwap', event => hydrate(event.target));
})();
