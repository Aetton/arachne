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

function safeEnvValue(value) {
  return winPath(value).replace(/%/g, '%%');
}

function writeWrapper(shimDir, name, realShell, wrapperScript, logFile, stepsDir, failedFile, stepPrefix) {
  if (!realShell) return false;

  const cmdPath = path.join(shimDir, `${name}.cmd`);

  const body =
    '@echo off\r\n' +
    'setlocal\r\n' +
    `set "ARACHNE_REAL_SHELL=${safeEnvValue(realShell)}"\r\n` +
    `set "ARACHNE_LOG_FILE=${safeEnvValue(logFile)}"\r\n` +
    `set "ARACHNE_STEPS_DIR=${safeEnvValue(stepsDir)}"\r\n` +
    `set "ARACHNE_FAILED_FILE=${safeEnvValue(failedFile)}"\r\n` +
    `set "ARACHNE_STEP_PREFIX=${safeEnvValue(stepPrefix || 'powershell')}"\r\n` +
    `"${winPath(realShell)}" -NoProfile -ExecutionPolicy Bypass -File "${winPath(wrapperScript)}" "%ARACHNE_REAL_SHELL%" "%ARACHNE_LOG_FILE%" "%ARACHNE_STEPS_DIR%" "%ARACHNE_FAILED_FILE%" "%ARACHNE_STEP_PREFIX%" %*\r\n` +
    'exit /b %ERRORLEVEL%\r\n';

  fs.writeFileSync(cmdPath, body, 'utf8');
  return true;
}

function wrapperSource() {
  return String.raw`
param(
  [Parameter(Position=0)][string]$Shell,
  [Parameter(Position=1)][string]$LogFile,
  [Parameter(Position=2)][string]$StepsDir,
  [Parameter(Position=3)][string]$FailedFile,
  [Parameter(Position=4)][string]$StepPrefix,
  [Parameter(ValueFromRemainingArguments=$true)][object[]]$ShellArgs
)

$ErrorActionPreference = "Continue"

try {
  $utf8 = New-Object System.Text.UTF8Encoding($false)
  [Console]::OutputEncoding = $utf8
  $OutputEncoding = $utf8
  chcp 65001 > $null 2>$null
} catch {
  # Best effort only. Logging must not fail because codepage tuning failed.
}

function Convert-ToSafeLabel {
  param(
    [string]$Value,
    [string]$Fallback = "step"
  )

  if ([string]::IsNullOrWhiteSpace($Value)) {
    return $Fallback
  }

  $clean = $Value.ToLowerInvariant()
  $clean = [regex]::Replace($clean, "[^a-z0-9_.-]+", "-")
  $clean = $clean.Trim("-")

  if ([string]::IsNullOrWhiteSpace($clean)) {
    return $Fallback
  }

  return $clean
}

function Get-NextStepIndex {
  param([string]$Dir)

  $indexFile = Join-Path $Dir "step-index.txt"
  $lockDir = Join-Path $Dir "step-index.lock"
  $waited = 0

  if (-not (Test-Path $Dir)) {
    New-Item -Path $Dir -ItemType Directory -Force | Out-Null
  }

  while ($true) {
    try {
      New-Item -Path $lockDir -ItemType Directory -ErrorAction Stop | Out-Null
      break
    } catch {
      Start-Sleep -Milliseconds 100
      $waited++
      if ($waited -gt 100) {
        return [int]((Get-Date).Ticks % 100000)
      }
    }
  }

  try {
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

    Set-Content -Path $indexFile -Value $next -Encoding UTF8
    return $next
  } finally {
    Remove-Item -Path $lockDir -Force -ErrorAction SilentlyContinue
  }
}

function Get-ScriptLabel {
  param([object[]]$Args)

  foreach ($arg in $Args) {
    $value = [string]$arg
    if ($value -match "\.(ps1|psm1)$") {
      $name = [System.IO.Path]::GetFileNameWithoutExtension($value)
      if ($name -match "^\d+$") {
        return "step-$name"
      }
      if (-not [string]::IsNullOrWhiteSpace($name)) {
        return $name
      }
    }
  }

  return "powershell"
}

function Write-BothLine {
  param(
    [object]$Value,
    [string]$GlobalLog,
    [string]$StepLog
  )

  if ($null -eq $Value) {
    $text = ""
  } else {
    $text = [string]$Value
  }

  Write-Output $text
  Add-Content -Path $GlobalLog -Value $text -Encoding UTF8
  Add-Content -Path $StepLog -Value $text -Encoding UTF8
}

if (-not (Test-Path $StepsDir)) {
  New-Item -Path $StepsDir -ItemType Directory -Force | Out-Null
}

$idx = Get-NextStepIndex -Dir $StepsDir
$prefix = Convert-ToSafeLabel -Value $StepPrefix -Fallback "powershell"
$scriptLabel = Convert-ToSafeLabel -Value (Get-ScriptLabel -Args $ShellArgs) -Fallback "powershell"
$stepName = "{0:D3}-{1}-{2}" -f $idx, $prefix, $scriptLabel
$stepLog = Join-Path $StepsDir ($stepName + ".log")
$stepStatus = Join-Path $StepsDir ($stepName + ".status")

$header = "===== ARACHNE STEP $stepName :: $(Get-Date -Format o) :: $Shell $($ShellArgs -join ' ') ====="
Write-BothLine -Value $header -GlobalLog $LogFile -StepLog $stepLog

try {
  & $Shell @ShellArgs *>&1 | ForEach-Object {
    Write-BothLine -Value $_ -GlobalLog $LogFile -StepLog $stepLog
  }

  $code = $LASTEXITCODE

  if ($null -eq $code) {
    if ($?) {
      $code = 0
    } else {
      $code = 1
    }
  }
} catch {
  Write-BothLine -Value ($_ | Out-String) -GlobalLog $LogFile -StepLog $stepLog
  $code = 1
}

if ($code -ne 0) {
  Set-Content -Path $stepStatus -Value "failed" -Encoding UTF8
  New-Item -Path $FailedFile -ItemType File -Force | Out-Null
} else {
  Set-Content -Path $stepStatus -Value "success" -Encoding UTF8
}

exit $code
`.trimStart();
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

  fs.writeFileSync(wrapperScript, wrapperSource(), 'utf8');

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
    stepPrefix,
  );

  const wrotePwsh = writeWrapper(
    shimDir,
    'pwsh',
    pwsh || powershell,
    wrapperScript,
    logFile,
    stepsDir,
    failedFile,
    stepPrefix,
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
