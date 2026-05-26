'use strict';

/**
 * webapp/npm install 完成后：在 Windows 上若尚无 .venv / .python310，
 * 则下载并静默安装官方 Python 3.10.11 到项目根目录 .python310，
 * 供 Electron main.js 的 findPython() 直接使用（避免仅存在「微软商店」python 占位符）。
 */
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

if (process.platform !== 'win32') {
  process.exit(0);
}

const root = path.resolve(__dirname, '..');
const ps1 = path.join(__dirname, 'bootstrap-python310.ps1');
const localPy = path.join(root, '.python310', 'python.exe');
const venvPy = path.join(root, '.venv', 'Scripts', 'python.exe');

if (fs.existsSync(localPy)) {
  console.log('[postinstall] Local Python 3.10 already present.');
  process.exit(0);
}

if (fs.existsSync(venvPy)) {
  console.log('[postinstall] .venv exists; skipping Python bootstrap.');
  process.exit(0);
}

if (!fs.existsSync(ps1)) {
  console.error('[postinstall] Missing script:', ps1);
  process.exit(1);
}

console.log('[postinstall] No Python in .venv/.python310; bootstrapping Python 3.10.11 (may take 1–2 minutes)...');
const r = spawnSync(
  'powershell.exe',
  ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ps1, '-Root', root],
  { stdio: 'inherit', windowsHide: false }
);
process.exit(r.status === null ? 1 : r.status);
