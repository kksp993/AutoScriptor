'use strict';

/**
 * 打包后自检：确认 app.asar 内含 package.json 的 main 入口（防 minimatch/glob 回归）。
 * 用法: node scripts/verify-pack.cjs [path-to-win-unpacked]
 * 默认: ../../dist_electron/win-unpacked
 */
const path = require('path');
const fs = require('fs');
const { listPackage, extractFile } = require('@electron/asar');

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

console.log('[verify-pack] OK', unpacked);
console.log('[verify-pack] main=', pkgMain, 'asar files=', files.length);
