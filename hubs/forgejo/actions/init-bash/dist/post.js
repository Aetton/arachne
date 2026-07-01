const fs = require('fs');
const path = require('path');

function state(name) {
  return process.env[`STATE_${name}`] || '';
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

function collectStepBlocks(stepsDir) {
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
        output: fs.readFileSync(logPath, 'utf8'),
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

  let blocks = collectStepBlocks(stepsDir);

  if (blocks.length === 0) {
    let output = '';

    if (logFile && fs.existsSync(logFile)) {
      output = fs.readFileSync(logFile, 'utf8');
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

  console.log(`Arachne init-bash post: sent ${blocks.length} log block(s).`);
}

main().catch((err) => {
  console.error(`Arachne init-bash post failed: ${err.stack || err.message}`);
  process.exitCode = 1;
});
