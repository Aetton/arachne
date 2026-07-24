(function () {
  var FALLBACK_METADATA = {
    spiders: [
      {name: 'ansible-local', kind: 'build', actions: ['build', 'deploy', 'run'], inputs: {playbook: {}, component: {}, target: {}, os: {}, version: {}}, description: 'Run ansible-playbook on the Arachne host.'},
      {name: 'ansible-ovirt', kind: 'provision', actions: ['provision'], inputs: {name: {}, os: {}}, description: 'Provision an oVirt VM through Ansible.'},
      {name: 'forgejo', kind: 'build', actions: ['build', 'run'], inputs: {repo: {}, workflow: {}, owner: {}, ref: {}, branch: {}, component: {}, version: {}}, description: 'Dispatch a Forgejo Actions workflow.'},
      {name: 'scenario', kind: 'build', actions: ['run'], inputs: {scenario: {}, params: {}}, description: 'Run another Arachne scenario as a child step.'},
      {name: 'tofu-proxmox', kind: 'provision', actions: ['provision'], inputs: {name: {}, os: {}, vcpus: {}, ram_mb: {}, disk_gb: {}}, description: 'Provision a Proxmox VM through OpenTofu.'}
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

    (metadata.spiders || []).forEach(function (spider) {
      var row = document.createElement('div');
      row.className = 'surface-2 rounded p-2 mt-2 text-xs';
      var title = document.createElement('div');
      title.appendChild(makeText('code', spider.name));
      title.appendChild(document.createTextNode(' '));
      title.appendChild(makeText('span', spider.kind || '', 'muted'));
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