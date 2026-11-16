async function connectionProbe(button, url, formData, status) {
  button.disabled = true;
  status.textContent = 'Checking…';
  status.style.color = '';
  try {
    const response = await fetch(url, {method:'POST', body:formData, credentials:'same-origin'});
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const result = await response.json();
    status.textContent = (result.ok ? '✓ ' : '✗ ') + (result.detail || result.stage);
    status.style.color = result.ok ? 'var(--ok-fg)' : 'var(--fail-fg)';
  } catch (error) {
    status.textContent = '✗ Request failed: ' + error.message;
    status.style.color = 'var(--fail-fg)';
  } finally { button.disabled = false; }
}
function testDraftProvider(button) {
  const form = document.getElementById('provider-form');
  connectionProbe(button, '/api/admin/secrets/provider/test',
                  new FormData(form), document.getElementById('provider-test-status'));
}
function testService(button, service) {
  const row = button.closest('.secret-service');
  const select = row.querySelector('select');
  const status = row.querySelector('.connection-test-status');
  if (!select.value) { status.textContent = 'Select credential first'; return; }
  const data = new FormData();
  data.set('service', service);
  data.set('credential_slug', select.value);
  connectionProbe(button, '/api/admin/secrets/service/test', data, status);
}

const credentialProfiles = {
  'ssh': {caption:'SSH access to a target host',fields:['username','private_key','password','known_hosts','port'],connection:'ssh',port:'22',summary:'key or password',authSwitch:true},
  'winrm': {caption:'WinRM access to a Windows target',fields:['username','password','port'],connection:'winrm',port:'5985',summary:'password'},
  'git-ssh': {caption:'SSH key for a Git repository',fields:['username','private_key','known_hosts'],connection:'ssh',port:'',summary:'private key'},
  'git-token': {caption:'Token authentication for a Git repository',fields:['username','token'],connection:'',port:'',summary:'token'},
  'token': {caption:'Single API or service token',fields:['token'],connection:'',port:'',summary:'token'},
  'basic': {caption:'Username and password authentication',fields:['username','password'],connection:'',port:'',summary:'password'}
};
let credentialAuth='key';

function toggleProviderKind(){var vault=document.getElementById('provider-kind').value==='vault';document.getElementById('vault-fields').classList.toggle('hidden',!vault);document.getElementById('database-note').classList.toggle('hidden',vault)}
function toggleVaultAuth(){var app=document.getElementById('provider-auth').value==='approle';document.getElementById('vault-token-fields').classList.toggle('hidden',app);document.getElementById('vault-approle-fields').classList.toggle('hidden',!app)}
function openProvider(){var f=document.getElementById('provider-form');f.reset();document.getElementById('provider-original').value='';document.getElementById('provider-kind').value='database';document.getElementById('provider-mount').value='secret';document.getElementById('provider-base-path').value='arachne';document.getElementById('provider-token-ref').value='VAULT_TOKEN';document.getElementById('provider-secret-ref').value='VAULT_SECRET_ID';document.getElementById('provider-enabled').checked=true;document.getElementById('provider-verify').checked=true;toggleProviderKind();toggleVaultAuth();document.getElementById('provider-dialog').showModal()}
function editProvider(btn){var p=JSON.parse(btn.dataset.provider),c=p.config||{};openProvider();document.getElementById('provider-original').value=p.slug;document.getElementById('provider-slug').value=p.slug;document.getElementById('provider-label').value=p.label;document.getElementById('provider-kind').value=p.kind;document.getElementById('provider-address').value=c.address||'';document.getElementById('provider-namespace').value=c.namespace||'';document.getElementById('provider-mount').value=c.mount||'secret';document.getElementById('provider-base-path').value=c.base_path||'arachne';document.getElementById('provider-mode').value=c.mode||'read-write';document.getElementById('provider-auth').value=c.auth_method||'token';document.getElementById('provider-token-source').value=c.token_source||'env';document.getElementById('provider-token-ref').value=c.token_ref||'VAULT_TOKEN';document.getElementById('provider-role-id').value=c.role_id||'';document.getElementById('provider-secret-source').value=c.secret_id_source||'env';document.getElementById('provider-secret-ref').value=c.secret_id_ref||'VAULT_SECRET_ID';document.getElementById('provider-enabled').checked=!!p.enabled;document.getElementById('provider-verify').checked=c.verify_tls!==false;toggleProviderKind();toggleVaultAuth()}

document.getElementById('provider-label')?.addEventListener('input', function() {
  const slug=document.getElementById('provider-slug');
  if (!document.getElementById('provider-original').value) {
    slug.value=this.value.toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0,64);
  }
});
document.getElementById('provider-form')?.addEventListener('submit', function() {
  const slug=document.getElementById('provider-slug');
  if (!slug.value) slug.value='storage-'+Date.now().toString(36);
});
function setCredentialAuth(mode){
  credentialAuth=mode;
  const kind=document.getElementById('credential-kind').value;
  const switcher=document.getElementById('credential-auth-switch');
  document.getElementById('credential-auth-key').classList.toggle('active',mode==='key');
  document.getElementById('credential-auth-password').classList.toggle('active',mode==='password');
  if(kind==='ssh'){
    document.querySelector('[data-credential-field="private_key"]').classList.toggle('hidden',mode!=='key');
    document.querySelector('[data-credential-field="password"]').classList.toggle('hidden',mode!=='password');
  }
  switcher.classList.toggle('hidden',kind!=='ssh');
}

function syncCredentialType(preservePort=false){
  const kind=document.getElementById('credential-kind').value;
  const profile=credentialProfiles[kind]||credentialProfiles.token;
  document.querySelectorAll('[data-credential-field]').forEach(el=>el.classList.toggle('hidden',!profile.fields.includes(el.dataset.credentialField)));
  document.getElementById('credential-type-caption').textContent=profile.caption;
  document.getElementById('credential-secret-summary').textContent=profile.summary;
  document.getElementById('credential-connection').value=profile.connection;
  const port=document.getElementById('credential-port');
  if(!preservePort || !port.value) port.value=profile.port;
  document.getElementById('credential-connection-block').classList.toggle('hidden',!profile.fields.includes('port')&&!profile.fields.includes('known_hosts'));
  document.getElementById('credential-auth-switch').classList.toggle('hidden',!profile.authSwitch);
  if(profile.authSwitch) setCredentialAuth(credentialAuth);
}

function showSecretPanel(which) {
  for (const key of ['credentials','services','storage']) {
    const panel = document.getElementById('secrets-panel-' + key);
    panel.hidden = key !== which;
  }
  document.querySelectorAll('.secrets-tab').forEach(tab => {
    const active = tab.dataset.panel === which;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
  });
  try { history.replaceState(null, '', '#' + which); } catch (_) {}
}

function confirmDeleteCredential(form, label) {
  return window.confirm(
    'Удалить доступ «' + label + '»?\\n\\n' +
    'Если credential используется сервисом или гипервизором, удаление будет заблокировано.\\n' +
    'Секретное значение также удалится из хранилища, если больше никем не используется.'
  );
}

function filterSecretCredentials() {
  const q = document.getElementById('credential-search').value.toLocaleLowerCase().trim();
  let visible = 0;
  document.querySelectorAll('.secret-credential[data-search]').forEach(card => {
    const matched = !q || card.dataset.search.includes(q);
    card.hidden = !matched;
    if (matched) visible++;
  });
  const noResults = document.getElementById('credentials-no-results');
  noResults.hidden = visible !== 0 || document.querySelectorAll('.secret-credential[data-search]').length === 0;
}

function setCredentialStep(n) {
  document.getElementById('credential-step-1').hidden = n !== 1;
  document.getElementById('credential-step-2').hidden = n !== 2;
  document.getElementById('credential-step-label-1').classList.toggle('is-active', n === 1);
  document.getElementById('credential-step-label-2').classList.toggle('is-active', n === 2);
  document.getElementById('credential-back').hidden = n === 1;
  document.getElementById('credential-next').hidden = n !== 1;
  document.getElementById('credential-submit').hidden = n !== 2;
}

function advanceCredential() {
  const form = document.getElementById('credential-form');
  for (const el of form.querySelectorAll('#credential-step-1 input, #credential-step-1 textarea, #credential-step-1 select')) {
    if (el.required && !el.checkValidity()) { el.reportValidity(); el.focus(); return; }
  }
  const label = document.getElementById('credential-label').value.trim();
  if (!label) { document.getElementById('credential-label').reportValidity(); return; }
  const slug = document.getElementById('credential-slug');
  if (!slug.value.trim()) {
    slug.value = label.toLowerCase()
      .replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0,64);
  }
  if (!slug.value) {
    const kind = document.getElementById('credential-kind').value;
    slug.value = kind + '-' + Date.now().toString(36);
  }
  const ref = document.getElementById('credential-secret-ref');
  if (!ref.value) ref.value = 'credentials/' + slug.value;
  setCredentialStep(2);
}

function openCredential(kind='basic') {
  const form = document.getElementById('credential-form');
  form.reset();
  credentialAuth='key';
  document.getElementById('credential-original').value='';
  document.getElementById('credential-kind').value=kind;
  document.getElementById('credential-dialog-title').textContent='Новый доступ';
  document.getElementById('credential-slug').value='';
  document.getElementById('credential-secret-ref').value='';
  form.querySelector('.credential-advanced').open=false;
  setCredentialStep(1);
  syncCredentialType(false);
  document.getElementById('credential-dialog').showModal();
}

function editCredential(btn) {
  const c=JSON.parse(btn.dataset.credential),m=c.metadata||{};
  openCredential(c.kind);
  document.getElementById('credential-dialog-title').textContent='Редактирование: '+c.label;
  document.getElementById('credential-original').value=c.slug;
  document.getElementById('credential-slug').value=c.slug;
  document.getElementById('credential-label').value=c.label;
  document.getElementById('credential-kind').value=c.kind;
  document.getElementById('credential-username').value=c.username||'';
  document.getElementById('credential-provider').value=c.provider;
  document.getElementById('credential-secret-ref').value=c.secret_ref;
  document.getElementById('credential-port').value=m.port||'';
  syncCredentialType(true);
}
if (['#services','#storage','#credentials'].includes(location.hash)) showSecretPanel(location.hash.slice(1));

document.getElementById('credential-slug')?.addEventListener('input',function(){
  const ref=document.getElementById('credential-secret-ref');
  if (!document.getElementById('credential-original').value) ref.value='credentials/'+this.value;
});
document.getElementById('credential-form')?.addEventListener('submit', function(event) {
  if (document.getElementById('credential-step-2').hidden) {
    event.preventDefault();
    advanceCredential();
  }
});
