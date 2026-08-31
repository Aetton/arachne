(function () {
  var FALLBACK_METADATA = {
    families: ['weave', 'brood', 'command'],
    spiders: [
      {name: 'ansible-local', family: 'command', actions: ['command'], inputs: {playbook: {}, component: {}, target: {}, os: {}, version: {}}, description: 'Run ansible-playbook on a target or locally.'},
      {name: 'ansible-ovirt', family: 'brood', actions: ['brood'], inputs: {name: {}, os: {}}, description: 'Create an oVirt VM through Ansible.'},
      {name: 'forgejo', family: 'weave', actions: ['weave'], inputs: {repo: {}, workflow: {}, owner: {}, ref: {}, branch: {}, component: {}, version: {}}, description: 'Dispatch a Forgejo Actions workflow.'},
      {name: 'scenario', family: 'command', actions: ['run'], inputs: {scenario: {}, params: {}}, description: 'Run another Arachne scenario as a child step.'},
      {name: 'tofu-proxmox', family: 'brood', actions: ['brood', 'destroy'], inputs: {name: {}, os: {}, image: {}, lifetime: {}, resources: {}}, description: 'Create or destroy a Proxmox stand through OpenTofu.'}
    ]
  };

  function makeText(tag, text, className) {
    var node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function renderCatalog(metadata) {
    var reference = document.querySelector('.dsl-reference');
    if (!reference) return;
    var existing = document.getElementById('dsl-plugin-catalog');
    if (existing) existing.remove();

    var block = document.createElement('div');
    block.id = 'dsl-plugin-catalog';
    block.style.marginTop = '1rem';
    block.appendChild(makeText('h3', 'Installed spiders', 'text-sm font-semibold'));

    var families = metadata.families || ['weave', 'brood', 'command'];
    block.appendChild(makeText('div', 'families: ' + families.join(', '), 'muted text-xs mt-1'));

    (metadata.spiders || []).forEach(function (spider) {
      var row = document.createElement('div');
      row.className = 'surface-2 rounded p-2 mt-2 text-xs';
      var title = document.createElement('div');
      title.appendChild(makeText('code', spider.name));
      title.appendChild(document.createTextNode(' '));
      title.appendChild(makeText('span', spider.family || '', 'muted'));
      row.appendChild(title);
      row.appendChild(makeText('div', 'actions: ' + (spider.actions || ['run']).join(', '), 'muted mt-1'));
      var inputs = Object.keys(spider.inputs || {});
      if (inputs.length) row.appendChild(makeText('div', 'with: ' + inputs.join(', '), 'muted mt-1'));
      if (spider.description) row.appendChild(makeText('div', spider.description, 'muted mt-1'));
      block.appendChild(row);
    });
    reference.appendChild(block);
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
