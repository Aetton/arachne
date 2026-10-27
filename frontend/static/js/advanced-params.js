/* invalid does not bubble. Capture it before the browser focuses a field inside
   a collapsed details element, including forms inserted later by HTMX. */
(function () {
  'use strict';
  document.addEventListener('invalid', function (event) {
    var target = event.target;
    if (!target || !target.closest) return;
    var section = target.closest('[data-advanced-params]');
    if (section) section.open = true;
  }, true);
})();
