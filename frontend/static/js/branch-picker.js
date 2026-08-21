(function () {
  'use strict';

  function initPicker(root) {
    if (!root || root.dataset.branchPickerReady === 'true') return;
    root.dataset.branchPickerReady = 'true';

    var search = root.querySelector('[data-branch-search]');
    var value = root.querySelector('[data-branch-value]');
    var menu = root.querySelector('[data-branch-menu]');
    var empty = root.querySelector('[data-branch-empty]');
    var options = Array.from(root.querySelectorAll('[data-branch-option]'));
    var activeIndex = -1;

    if (!search || !value || !menu) return;

    function visibleOptions() {
      return options.filter(function (option) { return !option.hidden; });
    }

    function setExpanded(expanded) {
      root.classList.toggle('is-open', expanded);
      search.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      menu.hidden = !expanded;
      if (!expanded) {
        activeIndex = -1;
        options.forEach(function (option) { option.classList.remove('is-active'); });
      }
    }

    function setActive(index) {
      var visible = visibleOptions();
      options.forEach(function (option) { option.classList.remove('is-active'); });
      if (!visible.length) {
        activeIndex = -1;
        return;
      }
      activeIndex = (index + visible.length) % visible.length;
      var option = visible[activeIndex];
      option.classList.add('is-active');
      option.scrollIntoView({ block: 'nearest' });
      search.setAttribute('aria-activedescendant', option.id);
    }

    function selectOption(option) {
      if (!option) return;
      var branch = option.dataset.value || option.textContent.trim();
      value.value = branch;
      search.value = branch;
      search.setCustomValidity('');
      options.forEach(function (item) {
        item.setAttribute('aria-selected', item === option ? 'true' : 'false');
      });
      setExpanded(false);
      search.focus();
      search.dispatchEvent(new CustomEvent('branchchange', {
        bubbles: true,
        detail: { value: branch }
      }));
    }

    function filter(query) {
      var needle = query.trim().toLocaleLowerCase();
      var count = 0;
      options.forEach(function (option) {
        var branch = (option.dataset.value || option.textContent).toLocaleLowerCase();
        var matches = !needle || branch.includes(needle);
        option.hidden = !matches;
        if (matches) count += 1;
      });
      if (empty) empty.hidden = count !== 0;
      activeIndex = -1;
      options.forEach(function (option) { option.classList.remove('is-active'); });
    }

    search.addEventListener('focus', function () {
      filter(search.value === value.value ? '' : search.value);
      setExpanded(true);
    });

    search.addEventListener('click', function () {
      if (!root.classList.contains('is-open')) {
        filter(search.value === value.value ? '' : search.value);
        setExpanded(true);
      }
    });

    search.addEventListener('input', function () {
      value.value = '';
      search.setCustomValidity('');
      filter(search.value);
      setExpanded(true);
    });

    search.addEventListener('keydown', function (event) {
      var visible = visibleOptions();
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        if (!root.classList.contains('is-open')) setExpanded(true);
        setActive(activeIndex + 1);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        if (!root.classList.contains('is-open')) setExpanded(true);
        setActive(activeIndex <= 0 ? visible.length - 1 : activeIndex - 1);
      } else if (event.key === 'Enter' && root.classList.contains('is-open')) {
        var active = visible[activeIndex];
        if (active) {
          event.preventDefault();
          selectOption(active);
        } else {
          var exact = options.find(function (option) {
            return (option.dataset.value || '').toLocaleLowerCase() === search.value.trim().toLocaleLowerCase();
          });
          if (exact) {
            event.preventDefault();
            selectOption(exact);
          }
        }
      } else if (event.key === 'Escape') {
        if (root.classList.contains('is-open')) {
          event.preventDefault();
          search.value = value.value;
          filter('');
          setExpanded(false);
        }
      }
    });

    options.forEach(function (option) {
      option.addEventListener('mousedown', function (event) { event.preventDefault(); });
      option.addEventListener('click', function () { selectOption(option); });
    });

    var form = root.closest('form');
    if (form) {
      form.addEventListener('submit', function (event) {
        if (value.value) return;
        var exact = options.find(function (option) {
          return (option.dataset.value || '').toLocaleLowerCase() === search.value.trim().toLocaleLowerCase();
        });
        if (exact) {
          selectOption(exact);
          return;
        }
        event.preventDefault();
        search.setCustomValidity('Выберите ветку из списка.');
        search.reportValidity();
        setExpanded(true);
      });
    }
  }

  function initAll(scope) {
    (scope || document).querySelectorAll('[data-branch-picker]').forEach(initPicker);
  }

  document.addEventListener('DOMContentLoaded', function () { initAll(document); });
  document.body.addEventListener('htmx:afterSwap', function (event) { initAll(event.target); });
  document.addEventListener('click', function (event) {
    document.querySelectorAll('[data-branch-picker].is-open').forEach(function (root) {
      if (!root.contains(event.target)) {
        var search = root.querySelector('[data-branch-search]');
        var value = root.querySelector('[data-branch-value]');
        var menu = root.querySelector('[data-branch-menu]');
        if (search && value) search.value = value.value;
        root.classList.remove('is-open');
        if (menu) menu.hidden = true;
      }
    });
  });
})();
