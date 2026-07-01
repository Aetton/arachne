const fs = require('fs');
const os = require('os');
const path = require('path');

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

function pathCandidates(cmd) {
  return (process.env.PATH || '')
    .split(path.delimiter)
    .filter(Boolean)
    .map((dir) => path.join(dir, cmd));
}

function firstExecutable(paths) {
  const seen = new Set();

  for (const p of paths) {
    if (!p || seen.has(p)) continue;
    seen.add(p);

    try {
      const stat = fs.statSync(p);
      fs.accessSync(p, fs.constants.X_OK);

      if (stat.isFile() || stat.isSymbolicLink()) return p;
    } catch (_) {
      // ignore missing or non-executable paths
    }
  }

  return '';
}

function shellSingleQuote(value) {
  return `'${String(value).replace(/'/g, `'"'"'`)}'`;
}

function safeLabel(value) {
  const cleaned = String(value || 'shell')
    .toLowerCase()
    .replace(/[^a-z0-9_.-]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return cleaned || 'shell';
}

function writeShim(shimDir, name, realShell, wrapperScript, logFile, stepsDir, failedFile, stepPrefix) {
  if (!realShell) return false;

  const shimPath = path.join(shimDir, name);
  const shellLabel = safeLabel(name);
  const prefix = safeLabel(stepPrefix || name);

  const body = [
    '#!/bin/sh',
    'set -eu',
    `real_shell=${shellSingleQuote(realShell)}`,
    '',
    'if [ "${ARACHNE_SHELL_WRAPPER_ACTIVE:-}" = "1" ]; then',
    '  exec "$real_shell" "$@"',
    'fi',
    '',
    `export ARACHNE_REAL_SHELL=${shellSingleQuote(realShell)}`,
    `export ARACHNE_LOG_FILE=${shellSingleQuote(logFile)}`,
    `export ARACHNE_STEPS_DIR=${shellSingleQuote(stepsDir)}`,
    `export ARACHNE_FAILED_FILE=${shellSingleQuote(failedFile)}`,
    `exec ${shellSingleQuote(wrapperScript)} ${shellSingleQuote(realShell)} ${shellSingleQuote(logFile)} ${shellSingleQuote(stepsDir)} ${shellSingleQuote(failedFile)} ${shellSingleQuote(prefix)} ${shellSingleQuote(shellLabel)} "$@"`,
    '',
  ].join('\n');

  fs.writeFileSync(shimPath, body, { encoding: 'utf8', mode: 0o755 });
  fs.chmodSync(shimPath, 0o755);
  return true;
}

function wrapperSource(bash) {
  return [
    `#!${bash}`,
    'set +e',
    '',
    'REAL_SHELL="${1:-}"',
    'LOG_FILE="${2:-}"',
    'STEPS_DIR="${3:-}"',
    'FAILED_FILE="${4:-}"',
    'STEP_PREFIX="${5:-shell}"',
    'SHELL_LABEL="${6:-shell}"',
    'shift 6 || true',
    '',
    'sanitize_label() {',
    '  local value="$1"',
    '  value="${value,,}"',
    '  value="$(printf \'%s\' "$value" | sed -E \'s/[^a-z0-9_.-]+/-/g; s/^-+//; s/-+$//\')"',
    '  if [[ -z "$value" ]]; then',
    '    printf \'shell\'',
    '  else',
    '    printf \'%s\' "$value"',
    '  fi',
    '}',
    '',
    'next_step_id() {',
    '  local dir="$1"',
    '  local index_file="$dir/step-index.txt"',
    '  local lock_dir="$dir/step-index.lock"',
    '  local current=0',
    '  local next=1',
    '  local waited=0',
    '',
    '  mkdir -p "$dir"',
    '',
    '  until mkdir "$lock_dir" 2>/dev/null; do',
    '    sleep 0.1',
    '    waited=$((waited + 1))',
    '    if (( waited > 100 )); then',
    '      printf \'%s-%s-%s\' "$(date +%s%N 2>/dev/null || date +%s)" "$$" "${RANDOM:-0}"',
    '      return 0',
    '    fi',
    '  done',
    '',
    '  if [[ -f "$index_file" ]]; then',
    '    current="$(cat "$index_file" 2>/dev/null || printf \'0\')"',
    '    if ! [[ "$current" =~ ^[0-9]+$ ]]; then',
    '      current=0',
    '    fi',
    '  fi',
    '',
    '  next=$((current + 1))',
    '  printf \'%s\\n\' "$next" > "$index_file"',
    '  rmdir "$lock_dir" 2>/dev/null || true',
    '',
    '  printf \'%03d\' "$next"',
    '}',
    '',
    'write_status() {',
    '  local path="$1"',
    '  local status="$2"',
    '  printf \'%s\\n\' "$status" > "$path"',
    '}',
    '',
    'mkdir -p "$STEPS_DIR"',
    '',
    'STEP_PREFIX="$(sanitize_label "$STEP_PREFIX")"',
    'SHELL_LABEL="$(sanitize_label "$SHELL_LABEL")"',
    'STEP_ID="$(next_step_id "$STEPS_DIR")"',
    'STEP_NAME="${STEP_ID}-${STEP_PREFIX}-${SHELL_LABEL}"',
    'STEP_LOG="$STEPS_DIR/$STEP_NAME.log"',
    'STEP_STATUS="$STEPS_DIR/$STEP_NAME.status"',
    '',
    '{',
    '  printf \'===== ARACHNE STEP %s :: %s :: %s\' "$STEP_NAME" "$(date -Iseconds 2>/dev/null || date)" "$REAL_SHELL"',
    '  for arg in "$@"; do',
    '    printf \' %q\' "$arg"',
    '  done',
    '  printf \' =====\\n\'',
    '} | tee -a "$LOG_FILE" "$STEP_LOG"',
    '',
    'ARACHNE_SHELL_WRAPPER_ACTIVE=1 "$REAL_SHELL" "$@" > >(tee -a "$LOG_FILE" "$STEP_LOG") 2>&1',
    'CODE=$?',
    '',
    'if [[ "$CODE" -ne 0 ]]; then',
    '  write_status "$STEP_STATUS" "failed"',
    '  : > "$FAILED_FILE"',
    'else',
    '  write_status "$STEP_STATUS" "success"',
    'fi',
    '',
    'exit "$CODE"',
    '',
  ].join('\n');
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

  const stepPrefix =
    getInput('step') ||
    process.env.ARACHNE_STEP ||
    'shell';

  const settle =
    (getInput('settle') || 'true').toLowerCase() !== 'false';

  const artifactsPath =
    getInput('artifacts-path') ||
    '.arachne/artifacts.json';

  saveState('enabled', callback && token ? 'true' : 'false');
  saveState('callback', callback);
  saveState('token', token);
  saveState('settle', settle ? 'true' : 'false');
  saveState('artifactsPath', artifactsPath);

  if (!callback || !token) {
    console.log('Arachne init-bash: no callback/token found; running as noop.');
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
  const wrapperScript = path.join(shimDir, 'arachne-shell-wrapper.sh');

  const bash = firstExecutable(pathCandidates('bash').concat([
    '/usr/local/bin/bash',
    '/usr/bin/bash',
    '/bin/bash',
  ]));

  if (!bash) {
    throw new Error('Arachne init-bash could not find bash for the wrapper runtime');
  }

  const sh = firstExecutable(pathCandidates('sh').concat([
    '/usr/local/bin/sh',
    '/usr/bin/sh',
    '/bin/sh',
  ]));

  fs.writeFileSync(wrapperScript, wrapperSource(bash), { encoding: 'utf8', mode: 0o755 });
  fs.chmodSync(wrapperScript, 0o755);

  const wroteBash = writeShim(
    shimDir,
    'bash',
    bash,
    wrapperScript,
    logFile,
    stepsDir,
    failedFile,
    stepPrefix,
  );

  const wroteSh = writeShim(
    shimDir,
    'sh',
    sh || bash,
    wrapperScript,
    logFile,
    stepsDir,
    failedFile,
    stepPrefix,
  );

  if (!wroteBash && !wroteSh) {
    throw new Error('Arachne init-bash could not find bash or sh');
  }

  addPath(shimDir);

  setEnv('ARACHNE_CALLBACK', callback);
  setEnv('ARACHNE_LOG_FILE', logFile);
  setEnv('ARACHNE_STEPS_DIR', stepsDir);
  setEnv('ARACHNE_FAILED_FILE', failedFile);

  saveState('logFile', logFile);
  saveState('stepsDir', stepsDir);
  saveState('failedFile', failedFile);

  console.log(`Arachne init-bash enabled: logs will mirror to ${logFile}`);
  console.log(`Arachne init-bash step logs: ${stepsDir}`);
  console.log(`Arachne init-bash shim: ${shimDir}`);
}

main();
