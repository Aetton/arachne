(() => {
  const groups = [...document.querySelectorAll('.manager-group')];
  const rows = [...document.querySelectorAll('#manager-scenarios tr')];
  const search = document.getElementById('manager-search');
  const status = document.getElementById('manager-status');
  const params = new URLSearchParams(location.search);
  let selected = params.get('group') || '', drag = null, saving = false;
  search.value = params.get('q') || '';
  function filter() {
    const q = search.value.trim().toLocaleLowerCase();
    if (!groups.some(g => g.dataset.group === selected)) selected = '';
    const chosen = groups.find(g => g.dataset.group === selected);
    document.getElementById('selected-group-title').textContent = chosen ? chosen.dataset.label : 'Все сценарии';
    let count = 0;
    rows.forEach(row => {
      row.hidden = !!((selected && row.dataset.group !== selected) || (q && !row.dataset.search.toLocaleLowerCase().includes(q)));
      if (!row.hidden) count++;
      const siblings = rows.filter(r => r.dataset.group === row.dataset.group);
      const i = siblings.indexOf(row);
      row.querySelector('[data-move="up"]').disabled = i === 0 || !!q;
      row.querySelector('[data-move="down"]').disabled = i === siblings.length - 1 || !!q;
      row.draggable = !q;
    });
    [...groups].reverse().forEach(g => {
      const ownMatch = (g.dataset.label + ' ' + g.dataset.group).toLocaleLowerCase().includes(q);
      const rowMatch = rows.some(r => r.dataset.group === g.dataset.group && r.dataset.search.toLocaleLowerCase().includes(q));
      g.hidden = !!q && !ownMatch && !rowMatch && ![...g.querySelectorAll('.manager-group')].some(c => !c.hidden);
      const details = g.querySelector('details');
      if (q && !g.hidden) details.open = true;
      details.querySelector('summary').classList.toggle('is-selected', g.dataset.group === selected);
    });
    document.getElementById('scenario-count').textContent = count;
    document.getElementById('manager-empty').hidden = count > 0;
    const url = new URL(location.href);
    selected ? url.searchParams.set('group', selected) : url.searchParams.delete('group');
    q ? url.searchParams.set('q', search.value) : url.searchParams.delete('q');
    history.replaceState(null, '', url);
  }
  async function save(payload) {
    if (saving) return;
    saving = true;
    document.body.classList.add('layout-saving');
    status.classList.remove('is-error');
    status.textContent = 'Сохраняю порядок…';
    try {
      const response = await fetch('/admin/scenarios/layout', {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)
      });
      if (!response.ok || response.redirected) {
        let detail = 'Не удалось сохранить. Обновите страницу и проверьте вход.';
        try { detail = (await response.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
      }
      location.reload();
    } catch (e) {
      status.textContent = e.message;
      status.classList.add('is-error');
      document.body.classList.remove('layout-saving');
      saving = false;
    }
  }
  search.addEventListener('input', filter);
  document.getElementById('all-scenarios').onclick = () => { selected = ''; filter(); };
  document.querySelectorAll('[data-select-group]').forEach(b => b.onclick = e => {
    e.preventDefault(); selected = b.dataset.selectGroup; filter();
  });
  ['expand','collapse'].forEach(action => {
    document.getElementById(action + '-groups').onclick = () => groups.forEach(g => { g.querySelector('details').open = action === 'expand'; });
  });
  groups.forEach(g => {
    const d = g.querySelector('details'), key = 'arachne-admin-group:' + g.dataset.group;
    try { const value = localStorage.getItem(key); if (value !== null) d.open = value === 'true'; } catch (_) {}
    d.addEventListener('toggle', e => { if (e.target !== d || search.value) return; try {localStorage.setItem(key, d.open);} catch (_) {} });
  });
  rows.forEach(row => row.querySelectorAll('[data-move]').forEach(b => b.onclick = () => {
    const siblings = rows.filter(r => r.dataset.group === row.dataset.group), i = siblings.indexOf(row);
    const before = b.dataset.move === 'up' ? siblings[i-1]?.dataset.scenarioSlug : siblings[i+2]?.dataset.scenarioSlug;
    save({kind:'scenario', slug:row.dataset.scenarioSlug, before:before || null});
  }));
  document.addEventListener('dragstart', e => {
    const g = e.target.closest('[data-drag-group]'), r = e.target.closest('[data-scenario-slug]');
    if (search.value.trim() || e.target.closest('input,select,textarea') || (!g && !r)) { e.preventDefault(); return; }
    drag = g ? {kind:'group',slug:g.dataset.dragGroup} : {kind:'scenario',slug:r.dataset.scenarioSlug};
    e.dataTransfer.setData('text/plain', JSON.stringify(drag)); e.dataTransfer.effectAllowed='move';
  });
  function target(e) {
    if (!drag) return null;
    return drag.kind === 'group' ? e.target.closest('[data-before-group],[data-drag-group],[data-drop-root]') : e.target.closest('#manager-scenarios tr');
  }
  document.addEventListener('dragover', e => { const t = target(e); if(t){e.preventDefault();t.classList.add('drop-active');} });
  document.addEventListener('dragleave', e => { const t = target(e); if(t)t.classList.remove('drop-active'); });
  document.addEventListener('dragend', () => { drag=null; document.querySelectorAll('.drop-active').forEach(e=>e.classList.remove('drop-active')); });
  document.addEventListener('drop', e => {
    const t = target(e); if(!t)return; e.preventDefault();
    document.querySelectorAll('.drop-active').forEach(e=>e.classList.remove('drop-active'));
    const payload = {...drag}; drag=null;
    if(payload.kind === 'group'){
      if(t.hasAttribute('data-before-group')){
        if(t.dataset.beforeGroup === payload.slug)return;
        payload.parent_group=t.closest('.manager-group').dataset.parent || null;
        payload.before=t.dataset.beforeGroup;
      } else payload.parent_group=t.dataset.dragGroup || null;
    } else {
      if(t.dataset.scenarioSlug === payload.slug)return;
      payload.before=t.dataset.scenarioSlug;
    }
    save(payload);
  });
  filter();
})();
