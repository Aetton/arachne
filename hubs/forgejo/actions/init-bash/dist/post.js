const fs = require('fs');
const path = require('path');

const DEFAULT_MAX_LOG_BYTES = 5 * 1024 * 1024;

function state(name) {
  return process.env[`STATE_${name}`] || '';
}

function maxLogBytes() {
  const raw = process.env.ARACHNE_MAX_LOG_BYTES || process.env.INPUT_MAX_LOG_BYTES || '';
  const parsed = Number.parseInt(raw, 10);

  if (Number.isFinite(parsed) && parsed > 0) return parsed;
  return DEFAULT_MAX_LOG_BYTES;
}

async function sendJson(url, token, payload) {
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Arachne-Token': token,
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Arachne callback failed ${response.status}: ${text}`);
  }
}

function readTextFileLimited(filePath, limitBytes) {
  const stat = fs.statSync(filePath);

  if (stat.size <= limitBytes) {
    return fs.readFileSync(filePath, 'utf8');
  }

  const fd = fs.openSync(filePath, 'r');

  try {
    const omittedBytes = stat.size - limitBytes;
    const buffer = Buffer.allocUnsafe(limitBytes);
    fs.readSync(fd, buffer, 0, limitBytes, 0);

    return [
      `[Arachne] log truncated after ${limitBytes} bytes; omitted ${omittedBytes} bytes.`,
      buffer.toString('utf8'),
    ].join('\n');
  } finally {
    fs.closeSync(fd);
  }
}

function readArtifacts(artifactsPath) {
  if (!artifactsPath) return [];

  const workspace = process.env.GITHUB_WORKSPACE || process.cwd();
  const abs = path.isAbsolute(artifactsPath)
    ? artifactsPath
    : path.join(workspace, artifactsPath);

  if (!fs.existsSync(abs)) return [];

  try {
    const data = JSON.parse(fs.readFileSync(abs, 'utf8'));
    return Array.isArray(data) ? data : [];
  } catch (err) {
    console.log(`Arachne init-bash: could not parse artifacts file ${abs}: ${err.message}`);
    return [];
  }
}

function readStatus(statusFile) {
  if (!fs.existsSync(statusFile)) return 'success';

  const raw = fs.readFileSync(statusFile, 'utf8').trim().toLowerCase();
  if (raw === 'failed' || raw === 'failure' || raw === 'error') return 'failed';
  if (raw === 'cancelled' || raw === 'canceled') return 'cancelled';
  return 'success';
}

function inferFinalStatus(stepBlocks, failedFile) {
  if (failedFile && fs.existsSync(failedFile)) return 'failed';

  if (stepBlocks.some((b) => b.status === 'failed')) return 'failed';
  if (stepBlocks.some((b) => b.status === 'cancelled')) return 'cancelled';

  return 'success';
}

function collectStepBlocks(stepsDir, limitBytes) {
  if (!stepsDir || !fs.existsSync(stepsDir)) return [];

  return fs
    .readdirSync(stepsDir)
    .filter((name) => name.endsWith('.log'))
    .sort()
    .map((name) => {
      const logPath = path.join(stepsDir, name);
      const base = name.replace(/\.log$/, '');
      const statusPath = path.join(stepsDir, `${base}.status`);

      return {
        step: base,
        status: readStatus(statusPath),
        output: readTextFileLimited(logPath, limitBytes),
      };
    });
}

async function main() {
  if (state('enabled') !== 'true') {
    console.log('Arachne init-bash post: noop.');
    return;
  }

  const callback = state('callback');
  const token = state('token');
  const settle = state('settle') !== 'false';
  const stepsDir = state('stepsDir');
  const logFile = state('logFile');
  const failedFile = state('failedFile');
  const artifactsPath = state('artifactsPath') || '.arachne/artifacts.json';
  const limitBytes = maxLogBytes();

  let blocks = collectStepBlocks(stepsDir, limitBytes);

  if (blocks.length === 0) {
    let output = '';

    if (logFile && fs.existsSync(logFile)) {
      output = readTextFileLimited(logFile, limitBytes);
    } else {
      output = [
        '[Arachne] init-bash did not capture Bash output.',
        'The runner may call the shell by absolute path, bypassing PATH shims.',
      ].join('\n');
    }

    blocks = [{
      step: 'runner-log',
      status: failedFile && fs.existsSync(failedFile) ? 'failed' : 'success',
      output,
    }];
  }

  for (const block of blocks) {
    await sendJson(`${callback}/signal`, token, {
      step: block.step,
      status: block.status,
      output: block.output,
    });
  }

  if (settle) {
    const status = inferFinalStatus(blocks, failedFile);
    const artifacts = readArtifacts(artifactsPath);

    await sendJson(`${callback}/status`, token, {
      status,
      artifacts,
    });
  }

  console.log(`Arachne init-bash post: sent ${blocks.length} log block(s), max log block size ${limitBytes} bytes.`);
}

main().catch((err) => {
  console.error(`Arachne init-bash post failed: ${err.stack || err.message}`);
  process.exitCode = 1;
});
