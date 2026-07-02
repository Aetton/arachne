const fs = require('fs');
const path = require('path');

const NEXUS_URL_RE = /(https?:\/\/[^\s'"<>]+\/repository\/([^/\s'"<>]+)\/([^\s'"<>]+))/gi;
const UPLOADED_URL_RE = /\bUploaded:\s*(https?:\/\/[^\s'"<>]+)/gi;
const TRAILING_URL_JUNK = '`' + "'" + '".,;:)]}';
const UPLOAD_STEP_HINTS = ['upload', 'publish', 'artifact', 'nexus'];

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

function cleanUrl(value) {
  return String(value || '').trim().replace(new RegExp(`[${TRAILING_URL_JUNK.replace(/[\\\]^]/g, '\\$&')}]+$`), '');
}

function artifactFromNexusUrl(rawUrl, sourceStep) {
  const cleaned = cleanUrl(rawUrl);

  let parsed;
  try {
    parsed = new URL(cleaned);
  } catch (_) {
    return null;
  }

  const marker = '/repository/';
  const markerIndex = parsed.pathname.indexOf(marker);
  if (markerIndex === -1) return null;

  const repoPath = decodeURIComponent(parsed.pathname.slice(markerIndex + marker.length));
  const sep = repoPath.indexOf('/');
  if (sep === -1) return null;

  const repo = repoPath.slice(0, sep);
  const artifactPath = repoPath.slice(sep + 1);
  if (!repo || !artifactPath) return null;

  return {
    name: artifactPath.split('/').pop() || 'artifact',
    type: 'nexus',
    location: `${repo}/${artifactPath}`,
    download_url: cleaned,
    metadata: {
      repo,
      path: artifactPath,
      source_step: sourceStep || '',
    },
  };
}

function isUploadBlock(block) {
  const step = String(block.step || '').toLowerCase();
  const output = String(block.output || '').toLowerCase();
  return UPLOAD_STEP_HINTS.some((hint) => step.includes(hint)) || output.includes('--upload-file');
}

function artifactsFromBlocks(blocks, mode) {
  const artifacts = [];
  const seen = new Set();

  function add(artifact) {
    if (!artifact) return;
    const key = artifact.download_url || artifact.location || artifact.name;
    if (!key || seen.has(key)) return;
    seen.add(key);
    artifacts.push(artifact);
  }

  for (const block of blocks) {
    const output = String(block.output || '');
    const sourceStep = String(block.step || '');
    const re = mode === 'uploaded' ? UPLOADED_URL_RE : NEXUS_URL_RE;
    re.lastIndex = 0;

    let match;
    while ((match = re.exec(output)) !== null) {
      add(artifactFromNexusUrl(match[1], sourceStep));
    }
  }

  return artifacts;
}

function recoverArtifactsFromLogs(blocks) {
  const uploadBlocks = blocks.filter(isUploadBlock);
  const scopes = uploadBlocks.length > 0 ? [uploadBlocks, blocks] : [blocks];

  for (const scopedBlocks of scopes) {
    const explicitUploads = artifactsFromBlocks(scopedBlocks, 'uploaded');
    if (explicitUploads.length > 0) return explicitUploads;

    const nexusUrls = artifactsFromBlocks(scopedBlocks, 'nexus');
    if (nexusUrls.length > 0) return nexusUrls;
  }

  return [];
}

function mergeArtifacts(primary, fallback) {
  const result = [];
  const seen = new Set();

  for (const artifact of [...primary, ...fallback]) {
    if (!artifact || typeof artifact !== 'object') continue;
    const key = artifact.download_url || artifact.location || artifact.name;
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(artifact);
  }

  return result;
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
    console.log(`Arachne init-pwsh: could not parse artifacts file ${abs}: ${err.message}`);
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
    console.log('Arachne init-pwsh post: noop.');
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
        '[Arachne] init-pwsh did not capture PowerShell output.',
        'The runner may call PowerShell by absolute path, bypassing PATH shims.',
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
    const artifacts = mergeArtifacts(readArtifacts(artifactsPath), recoverArtifactsFromLogs(blocks));

    await sendJson(`${callback}/status`, token, {
      status,
      artifacts,
    });
  }

  console.log(`Arachne init-pwsh post: sent ${blocks.length} log block(s).`);
}

main().catch((err) => {
  console.error(`Arachne init-pwsh post failed: ${err.stack || err.message}`);
  process.exitCode = 1;
});
