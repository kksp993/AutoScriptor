'use strict';

/**
 * 打包后自检：确认 app.asar 内含 package.json 的 main 入口（防 minimatch/glob 回归）。
 * 用法: node scripts/verify-pack.cjs [path-to-win-unpacked]
 * 默认: ../../dist_electron/win-unpacked
 */
const path = require('path');
const fs = require('fs');
const { listPackage, extractFile } = require('@electron/asar');
const yauzl = require('yauzl');

const defaultUnpacked = path.resolve(__dirname, '..', '..', 'dist_electron', 'win-unpacked');
const unpacked = path.resolve(process.argv[2] || defaultUnpacked);
const asarPath = path.join(unpacked, 'resources', 'app.asar');

if (!fs.existsSync(asarPath)) {
  console.error('[verify-pack] 缺少:', asarPath);
  process.exit(1);
}

let pkgMain = 'main.js';
try {
  const raw = extractFile(asarPath, 'package.json');
  pkgMain = JSON.parse(raw.toString('utf8')).main || pkgMain;
} catch (e) {
  console.error('[verify-pack] 无法读取 app.asar 内 package.json:', e.message);
  process.exit(1);
}

const files = listPackage(asarPath);
const norm = (f) => f.replace(/^\//, '').replace(/\\/g, '/');
const base = path.basename(pkgMain.replace(/\\/g, '/'));
const hasMain = files.some((f) => {
  const n = norm(f);
  return n === pkgMain.replace(/\\/g, '/') || n.endsWith('/' + base) || n === base;
});

if (!hasMain) {
  console.error('[verify-pack] 入口不在 app.asar 内:', pkgMain);
  console.error('[verify-pack] 文件数:', files.length);
  process.exit(1);
}

const backendZipCandidates = [
  path.join(unpacked, 'backend.zip'),
  path.join(unpacked, 'resources', 'backend.zip'),
];
const backendZip = backendZipCandidates.find((p) => fs.existsSync(p));

if (!backendZip) {
  console.error('[verify-pack] missing backend.zip. Expected one of:');
  for (const p of backendZipCandidates) console.error('  -', p);
  process.exit(1);
}

yauzl.open(backendZip, { lazyEntries: true }, (err, zipfile) => {
  if (err) {
    console.error('[verify-pack] cannot open backend.zip:', err.message);
    process.exit(1);
  }
  let hasEngine = false;
  let count = 0;
  zipfile.readEntry();
  zipfile.on('entry', (entry) => {
    if (!entry.fileName.endsWith('/')) {
      count += 1;
      const n = entry.fileName.replace(/\\/g, '/');
      if (n === 'autoscriptor-engine.exe' || n.endsWith('/autoscriptor-engine.exe')) {
        hasEngine = true;
      }
    }
    zipfile.readEntry();
  });
  zipfile.on('error', (e) => {
    console.error('[verify-pack] failed reading backend.zip:', e.message);
    process.exit(1);
  });
  zipfile.on('end', () => {
    if (!hasEngine) {
      console.error('[verify-pack] backend.zip is missing autoscriptor-engine.exe');
      process.exit(1);
    }
    console.log('[verify-pack] OK', unpacked);
    console.log('[verify-pack] main=', pkgMain, 'asar files=', files.length);
    console.log('[verify-pack] backend.zip=', backendZip, 'files=', count);
  });
});
