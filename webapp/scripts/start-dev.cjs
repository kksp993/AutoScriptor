'use strict';

const { spawn, execFileSync } = require('child_process');
const path = require('path');
const { StringDecoder } = require('string_decoder');

function forceUtf8Console() {
  if (process.platform !== 'win32') return;
  try {
    execFileSync(
      'cmd.exe',
      ['/d', '/s', '/c', 'chcp 65001 >nul'],
      { stdio: 'ignore', windowsHide: true, timeout: 2000 },
    );
  } catch (_) {
    // The app can still run; this only affects terminal rendering.
  }
}

function buildEnv() {
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;
  env.PYTHONIOENCODING = 'utf-8';
  env.PYTHONUTF8 = '1';
  env.LANG = env.LANG || 'C.UTF-8';
  env.LC_ALL = env.LC_ALL || 'C.UTF-8';
  return env;
}

function electronPath() {
  if (process.platform === 'win32') {
    return path.join(__dirname, '..', 'node_modules', 'electron', 'dist', 'electron.exe');
  }
  return require('electron');
}

forceUtf8Console();

const child = spawn(electronPath(), ['.'], {
  cwd: path.resolve(__dirname, '..'),
  stdio: ['inherit', 'pipe', 'pipe'],
  env: buildEnv(),
  windowsHide: false,
});

function pipeUtf8(readable, writable) {
  const decoder = new StringDecoder('utf8');
  readable.on('data', (chunk) => {
    writable.write(decoder.write(chunk));
  });
  readable.on('end', () => {
    const tail = decoder.end();
    if (tail) writable.write(tail);
  });
}

pipeUtf8(child.stdout, process.stdout);
pipeUtf8(child.stderr, process.stderr);

function stopChild(signal) {
  if (!child.pid) return;
  if (process.platform === 'win32') {
    try {
      execFileSync(
        'taskkill.exe',
        ['/PID', String(child.pid), '/T', '/F'],
        { stdio: 'ignore', windowsHide: true, timeout: 5000 },
      );
    } catch (_) {}
    return;
  }
  try { child.kill(signal); } catch (_) {}
}

for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.once(signal, () => {
    stopChild(signal);
  });
}

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});

child.on('error', (err) => {
  console.error('[start] Failed to launch Electron:', err);
  process.exit(1);
});
