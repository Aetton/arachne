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
    const out = child_process.execFileSync('where.exe', [cmd], { encoding: 'utf8' });
    return out
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
  } catch (_) {
    return [];
  }
}

function firstExisting(paths) {
  return paths.find((p) => {
    try {
      return fs.existsSync(p);
    } catch (_) {
      return false;
    }
  }) || '';
}

function winPath(value) {
  return String(value).replace(/"/g, '');
}

function writeWrapper(shimDir, name, realShell, wrapperScript, logFile, stepsDir, failedFile) {
  if (!realShell) return false;

  const cmdPath = path.join(shimDir, `${name}.cmd`);

  const body =
    '@echo off\r\n' +
    'setlocal\r\n' +
    `set "ARACHNE_REAL_SHELL=${winPath(realShell)}"\r\n` +
    `set "ARACHNE_LOG_FILE=${winPath(logFile)}"\r\n` +
    `set "ARACHNE_STEPS_DIR=${winPath(stepsDir)}"\r\n` +
    `set "ARACHNE_FAILED_FILE=${winPath(failedFile)}"\r\n` +
    `"${winPath(realShell)}" -NoProfile -ExecutionPolicy Bypass -File "${winPath(wrapperScript)}" "%ARACHNE_REAL_SHELL%" "%ARACHNE_LOG_FILE%" "%ARACHNE_STEPS_DIR%" "%ARACHNE_FAILED_FILE%" %*\r\n` +
    'exit /b %ERRORLEVEL%\r\n';

  fs.writeFileSync(cmdPath, body, 'utf8');
  return true;
}

function main() {
  const eventInputs = readEventInputs();

  const callback =
    getInput('callback') ||
    process.env.ARACHNE_CALLBACK ||
    eventInputs.arachne_callback ||
    '';

  const token =
    getInput('token') ||
    process.env.ARACHNE_TOKEN ||
    eventInputs.arachne_token ||
    '';

  const buildId =
    process.env.ARACHNE_BUILD_ID ||
    eventInputs.build_id ||
    '';

  const stepPrefix =
    getInput('step') ||
    process.env.ARACHNE_STEP ||
    'powershell';

  const settle =
    (getInput('settle') || 'true').toLowerCase() !== 'false';

  const artifactsPath =
    getInput('artifacts-path') ||
    '.arachne/artifacts.json';

  saveState('enabled', callback && token ? 'true' : 'false');
  saveState('callback', callback);
  saveState('token', token);
  saveState('stepPrefix', stepPrefix);
  saveState('settle', settle ? 'true' : 'false');
  saveState('artifactsPath', artifactsPath);

  if (!callback || !token) {
    console.log('Arachne init-pwsh: no callback/token found; running as noop.');
    return;
  }

  const tempRoot = process.env.RUNNER_TEMP || os.tmpdir();
  const workDir = path.join(tempRoot, `arachne-${Date.now()}`);
  const shimDir = path.join(workDir, 'shim');
  const stepsDir = path.join(workDir, 'steps');

  fs.mkdirSync(shimDir, { recursive: true });
  fs.mkdirSync(stepsDir, { recursive: true });

  const logFile = path.join(workDir, 'runner.log');
  const failedFile = path.join(workDir, 'failed');
  const wrapperScript = path.join(shimDir, 'arachne-pwsh-wrapper.ps1');

  const wrapper = `
param(
  [Parameter(Position=0)][string]$Shell,
  [Parameter(Position=1)][string]$LogFile,
  [Parameter(Position=2)][string]$StepsDir,
  [Parameter(Position=3)][string]$FailedFile,
  [Parameter(ValueFromRemainingArguments=$true)][object[]]$ShellArgs
)

$ErrorActionPreference = "Continue"

function Get-NextStepIndex {
  param([string]$Dir)

  $indexFile = Join-Path $Dir "step-index.txt"

  if (Test-Path $indexFile) {
    try {
      $current = [int](Get-Content -Path $indexFile -Raw)
      $next = $current + 1
    } catch {
      $next = 1
    }
  } else {
    $next = 1
  }

  Set-Content -Path $indexFile -Value $next
  return $next
}

function Write-Both {
  param(
    [string]$Text,
    [string]$GlobalLog,
    [string]$StepLog
  )

  $Text | Tee-Object -FilePath $GlobalLog -Append | Tee-Object -FilePath $StepLog -Append
}

if (-not (Test-Path $StepsDir)) {
  New-Item -Path $StepsDir -ItemType Directory -Force | Out-Null
}

$idx = Get-NextStepIndex -Dir $StepsDir
$stepName = "{0:D3}-powershell" -f $idx
$stepLog = Join-Path $StepsDir ($stepName + ".log")
$stepStatus = Join-Path $StepsDir ($stepName + ".status")

$header = "===== ARACHNE STEP $stepName :: $(Get-Date -Format o) :: $Shell $($ShellArgs -join ' ') ====="
Write-Both -Text $header -GlobalLog $LogFile -StepLog $stepLog

try {
  & $Shell @ShellArgs *>&1 |
    Tee-Object -FilePath $LogFile -Append |
    Tee-Object -FilePath $stepLog -Append

  $code = $LASTEXITCODE

  if ($null -eq $code) {
    if ($?) {
      $code = 0
    } else {
      $code = 1
    }
  }
} catch {
  $_ | Out-String |
    Tee-Object -FilePath $LogFile -Append |
    Tee-Object -FilePath $stepLog -Append

  $code = 1
}

if ($code -ne 0) {
  Set-Content -Path $stepStatus -Value "failed"
  New-Item -Path $FailedFile -ItemType File -Force | Out-Null
} else {
  Set-Content -Path $stepStatus -Value "success"
}

exit $code
`.trimStart();

  fs.writeFileSync(wrapperScript, wrapper, 'utf8');

  const powershell = firstExisting(which('powershell.exe').concat([
    'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe',
  ]));

  const pwsh = firstExisting(which('pwsh.exe'));

  const wrotePowerShell = writeWrapper(
    shimDir,
    'powershell',
    powershell,
    wrapperScript,
    logFile,
    stepsDir,
    failedFile,
  );

  const wrotePwsh = writeWrapper(
    shimDir,
    'pwsh',
    pwsh || powershell,
    wrapperScript,
    logFile,
    stepsDir,
    failedFile,
  );

  if (!wrotePowerShell && !wrotePwsh) {
    throw new Error('Arachne init-pwsh could not find powershell.exe or pwsh.exe');
  }

  addPath(shimDir);

  setEnv('ARACHNE_CALLBACK', callback);
  setEnv('ARACHNE_TOKEN', token);
  setEnv('ARACHNE_BUILD_ID', buildId);
  setEnv('ARACHNE_LOG_FILE', logFile);
  setEnv('ARACHNE_STEPS_DIR', stepsDir);
  setEnv('ARACHNE_FAILED_FILE', failedFile);

  saveState('logFile', logFile);
  saveState('stepsDir', stepsDir);
  saveState('failedFile', failedFile);

  console.log(`Arachne init-pwsh enabled: logs will mirror to ${logFile}`);
  console.log(`Arachne init-pwsh step logs: ${stepsDir}`);
  console.log(`Arachne init-pwsh shim: ${shimDir}`);
}

main();
