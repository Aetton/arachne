(() => {
  'use strict';

  function logText(viewer) {
    return Array.from(viewer.querySelectorAll('.log-line'))
      .map(line => line.dataset.raw || line.querySelector('.log-line-text')?.textContent || '')
      .join('\n');
  }

  async function writeClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (error) {
        console.warn('Arachne Clipboard API failed, using fallback', error);
      }
    }

    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.setAttribute('aria-hidden', 'true');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    textarea.style.top = '0';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);

    const selection = document.getSelection();
    const savedRanges = [];
    if (selection) {
      for (let i = 0; i < selection.rangeCount; i += 1) {
        savedRanges.push(selection.getRangeAt(i));
      }
    }

    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);

    let copied = false;
    try {
      copied = document.execCommand('copy');
    } catch (error) {
      console.warn('Arachne legacy clipboard fallback failed', error);
    } finally {
      textarea.remove();
      if (selection) {
        selection.removeAllRanges();
        savedRanges.forEach(range => selection.addRange(range));
      }
    }
    return copied;
  }

  function flash(button, ok) {
    const previous = button.innerHTML;
    button.classList.toggle('copied', ok);
    button.innerHTML = ok
      ? '<i class="ti ti-check"></i> Copied'
      : '<i class="ti ti-alert-triangle"></i> Copy failed';
    setTimeout(() => {
      button.classList.remove('copied');
      button.innerHTML = previous;
    }, ok ? 1200 : 1800);
  }

  document.addEventListener('click', async event => {
    const button = event.target.closest?.('[data-log-action="copy"]');
    if (!button) return;

    const viewer = button.closest('.log-viewer');
    if (!viewer) return;

    // Override the older per-viewer handler. This listener runs in capture phase,
    // so broken Clipboard API handling in live-log-viewer.js cannot swallow the click.
    event.preventDefault();
    event.stopImmediatePropagation();

    const text = logText(viewer);
    const copied = text ? await writeClipboard(text) : false;
    flash(button, copied);
  }, true);
})();
