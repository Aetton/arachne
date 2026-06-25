const fs = require('fs');
const os = require('os');
const path = require('path');
const child_process = require('child_process');

function appendFileEnv(name, value) {
  const file = process.env[name];
  if (file) fs.appendFileSync(file, `${value}\n`);
}

function setEnv(name, value) {
  appendFileEnv('GITHUB_ENV', `${name}=${value}`);
}

function addPath(value) {
  appendFileEnv('GITHUB_PATH', value);
}

function saveState(name, value) {
  appendFileEnv('GITHUB_STATE', `${name}=${value}`);
}

function getInput(name) {
  const key = `INPUT_${name.replace(/ /g, '_').replace(/-/g, '_').toUpperCase()}`;
  return process.env[key] || '';
}

function readEventInputs() {
  const eventPath = process.env.GITHUB_EVENT_PATH;
  if (!eventPath || !fs.existsSync(eventPath)) return {};
  try {
    const event = JSON.parse(fs.readFileSync(eventPath, 'utf8'));
    return event.inputs || event.workflow_dispatch?.inputs || {};
  } catch (_) {
    return {};
  }
}

function which(cmd) {
  try {
    const out = child_process.execFileSync('where.exe', [cmd], {encoding: 'utf8'});
    return out.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  } catch (_) {
    return [];
  }
}

function firstExisting(paths) {
  return paths.find(p => {
    try { return fs.existsSync(p); } catch (_) { return false; }
  }) || '';
}

function writeWrapper(shimDir, name, realShell, wrapperScript, logFile, failedFile) {
  if (!realShell) return false;
  const cmdPath = path.join(shimDir, `${name}.cmd`);
  const body = `@echo off
` +
    `setlocal
` +
    `set "ARACHNE_REAL_SHELL=${realShell}"
` +
    `set "ARACHNE_LOG_FILE=${logFile}"
` +
    `set "ARACHNE_FAILED_FILE=${failedFile}"
` +
    `"${realShell}" -NoProfile -ExecutionPolicy Bypass -File "${wrapperScript}" "%ARACHNE_REAL_SHELL%" "%ARACHNE_LOG_FILE%" "%ARACHNE_FAILED_FILE%" %*
` +
    `exit /b %ERRORLEVEL%
`;
  fs.writeFileSync(cmdPath, body, 'utf8');
  return true;
}

function main() {
  const eventInputs = readEventInputs();
  const callback = getInput('callback') || process.env.ARACHNE_CALLBACK || eventInputs.arachne_callback || '';
  const token = getInput('token') || process.env.ARACHNE_TOKEN || eventInputs.arachne_token || '';
  const buildId = process.env.ARACHNE_BUILD_ID || eventInputs.build_id || '';
  const step = getInput('step') || process.env.ARACHNE_STEP || 'runner-log';
  const settle = (getInput('settle') || 'true').toLowerCase() !== 'false';
  const artifactsPath = getInput('artifacts-path') || '.arachne/artifacts.json';

  saveState('enabled', callback && token ? 'true' : 'false');
  saveState('callback', callback);
  saveState('token', token);
  saveState('step', step);
  saveState('settle', settle ? 'true' : 'false');
  saveState('artifactsPath', artifactsPath);

  if (!callback || !token) {
    console.log('Arachne init-pwsh: no callback/token found; running as noop.');
    return;
  }

  const tempRoot = process.env.RUNNER_TEMP || os.tmpdir();
  const workDir = path.join(tempRoot, `arachne-${Date.now()}`);
  const shimDir = path.join(workDir, 'shim');
  fs.mkdirSync(shimDir, {recursive: true});

  const logFile = path.join(workDir, 'runner.log');
  const failedFile = path.join(workDir, 'failed');
  const wrapperScript = path.join(shimDir, 'arachne-pwsh-wrapper.ps1');

  const wrapper = `param(
` +
    `  [Parameter(Position=0)][string]$Shell,
` +
    `  [Parameter(Position=1)][string]$LogFile,
` +
    `  [Parameter(Position=2)][string]$FailedFile,
` +
    `  [Parameter(ValueFromRemainingArguments=$true)][object[]]$ShellArgs
` +
    `)
` +
    `$header = "`n===== ARACHNE SHELL $(Get-Date -Format o) :: $Shell $($ShellArgs -join ' ') ====="
` +
    `$header | Tee-Object -FilePath $LogFile -Append
` +
    `try {
` +
    `  & $Shell @ShellArgs *>&1 | Tee-Object -FilePath $LogFile -Append
` +
    `  $code = $LASTEXITCODE
` +
    `  if ($null -eq $code) { $code = if ($?) { 0 } else { 1 } }
` +
    `} catch {
` +
    `  $_ | Out-String | Tee-Object -FilePath $LogFile -Append
` +
    `  $code = 1
` +
    `}
` +
    `if ($code -ne 0) { New-Item -Path $FailedFile -ItemType File -Force | Out-Null }
` +
    `exit $code
`;
  fs.writeFileSync(wrapperScript, wrapper, 'utf8');

  const powershell = firstExisting(which('powershell.exe').concat([
    'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe'
  ]));
  const pwsh = firstExisting(which('pwsh.exe'));

  const wrotePowerShell = writeWrapper(shimDir, 'powershell', powershell, wrapperScript, logFile, failedFile);
  const wrotePwsh = writeWrapper(shimDir, 'pwsh', pwsh || powershell, wrapperScript, logFile, failedFile);

  if (!wrotePowerShell && !wrotePwsh) {
    throw new Error('Arachne init-pwsh could not find powershell.exe or pwsh.exe');
  }

  addPath(shimDir);
  setEnv('ARACHNE_CALLBACK', callback);
  setEnv('ARACHNE_TOKEN', token);
  setEnv('ARACHNE_BUILD_ID', buildId);
  setEnv('ARACHNE_LOG_FILE', logFile);
  setEnv('ARACHNE_FAILED_FILE', failedFile);

  saveState('logFile', logFile);
  saveState('failedFile', failedFile);

  console.log(`Arachne init-pwsh enabled: logs will mirror to ${logFile}`);
  console.log(`Arachne init-pwsh shim: ${shimDir}`);
}

main();
