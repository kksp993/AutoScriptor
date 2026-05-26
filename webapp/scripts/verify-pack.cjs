'use strict';

/**
 * Post-package release verifier.
 *
 * It checks both the Electron shell and the runtime payload that the HTML
 * installer will copy into the user's install root. Keep this script strict:
 * a package that passes here should at least contain the config/data/assets
 * needed for a first boot without relying on the developer machine.
 *
 * Usage: node scripts/verify-pack.cjs [path-to-win-unpacked]
 * Default: ../../dist_electron/win-unpacked
 */
const path = require('path');
const fs = require('fs');
const { listPackage, extractFile } = require('@electron/asar');
const yauzl = require('yauzl');

const defaultUnpacked = path.resolve(__dirname, '..', '..', 'dist_electron', 'win-unpacked');
const unpacked = path.resolve(process.argv[2] || defaultUnpacked);
const asarPath = path.join(unpacked, 'resources', 'app.asar');

function fail(message, details = []) {
  console.error('[verify-pack]', message);
  for (const d of details) console.error('  -', d);
  process.exit(1);
}

function note(message) {
  console.log('[verify-pack]', message);
}

function assertFile(file, label = file) {
  if (!fs.existsSync(file) || !fs.statSync(file).isFile()) {
    fail(`missing required file: ${label}`, [file]);
  }
}

function assertDir(dir, label = dir) {
  if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) {
    fail(`missing required directory: ${label}`, [dir]);
  }
}

function readJson(file, label) {
  assertFile(file, label);
  try {
    const data = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      fail(`${label} must be a JSON object`, [file]);
    }
    return data;
  } catch (e) {
    fail(`${label} is not valid JSON`, [`${file}: ${e.message}`]);
  }
  return {};
}

function walkFiles(root, out = []) {
  if (!fs.existsSync(root)) return out;
  const st = fs.statSync(root);
  if (st.isFile()) {
    out.push(root);
    return out;
  }
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    walkFiles(path.join(root, entry.name), out);
  }
  return out;
}

function rel(root, file) {
  return path.relative(root, file).replace(/\\/g, '/');
}

function validatePackagedConfig(dataRoot) {
  const cfg = readJson(path.join(dataRoot, 'config.json'), 'data/config.json');
  const tpl = readJson(path.join(dataRoot, 'config template.json'), 'data/config template.json');

  const required = ['app', 'emulator', 'ocr', 'deploy', 'accounts', 'current_account'];
  const missing = required.filter((k) => !(k in cfg));
  if (missing.length) {
    fail('data/config.json is missing required sections', missing);
  }
  if (!cfg.app || cfg.app.name !== 'ZmxyOL') {
    fail('data/config.json app.name must be ZmxyOL', [`got: ${cfg.app && cfg.app.name}`]);
  }
  if (!cfg.app || !('app_to_start' in cfg.app)) {
    fail('data/config.json is missing app.app_to_start');
  }
  if (!cfg.emulator || typeof cfg.emulator !== 'object') {
    fail('data/config.json emulator section must be an object');
  }
  for (const key of ['index', 'adb_addr', 'mumu_folder', 'emu_path', 'adb_path']) {
    if (!cfg.emulator || !(key in cfg.emulator)) {
      fail('data/config.json is missing emulator.' + key);
    }
  }
  if (!cfg.current_account || typeof cfg.current_account !== 'string') {
    fail('data/config.json must define current_account for first-run account creation');
  }

  const accountsDir = String((cfg.accounts && cfg.accounts.dir) || '').trim();
  if (accountsDir && path.isAbsolute(accountsDir)) {
    fail('data/config.json accounts.dir must not be an absolute developer-machine path', [accountsDir]);
  }
  if (JSON.stringify(cfg) !== JSON.stringify(tpl)) {
    fail('data/config.json must be generated from config template.json for release builds');
  }
}

function validateDataRoot(dataRoot) {
  assertDir(dataRoot, 'data');
  validatePackagedConfig(dataRoot);

  const uiMap = path.join(dataRoot, 'assets', 'config', 'ui_map.csv');
  assertFile(uiMap, 'data/assets/config/ui_map.csv');
  const header = fs.readFileSync(uiMap, 'utf8').split(/\r?\n/, 1)[0].trim();
  for (const col of ['key', 'text', 'left', 'top', 'width', 'height', 'img']) {
    if (!header.split(',').includes(col)) {
      fail('ui_map.csv header is missing required column', [col, uiMap]);
    }
  }

  assertFile(path.join(dataRoot, 'battle_character', 'hero.py'), 'data/battle_character/hero.py');

  const leakedAccountJson = walkFiles(path.join(dataRoot, 'accounts'))
    .filter((f) => f.toLowerCase().endsWith('.json'))
    .map((f) => rel(dataRoot, f));
  if (leakedAccountJson.length) {
    fail('packaged data must not contain user account JSON files', leakedAccountJson.slice(0, 20));
  }

  const leakedBytecode = walkFiles(dataRoot)
    .filter((f) => /\.(pyc|pyo)$/i.test(f) || rel(dataRoot, f).toLowerCase().includes('__pycache__/'))
    .map((f) => rel(dataRoot, f));
  if (leakedBytecode.length) {
    fail('packaged data must not contain Python bytecode/cache files', leakedBytecode.slice(0, 20));
  }
}

function inspectZip(zipPath) {
  return new Promise((resolve, reject) => {
    yauzl.open(zipPath, { lazyEntries: true }, (err, zipfile) => {
      if (err) return reject(err);
      const entries = new Set();
      let count = 0;
      let uncompressedBytes = 0;
      zipfile.readEntry();
      zipfile.on('entry', (entry) => {
        if (!entry.fileName.endsWith('/')) {
          const n = entry.fileName.replace(/\\/g, '/').replace(/^\/+/, '');
          entries.add(n);
          count += 1;
          uncompressedBytes += Number(entry.uncompressedSize || 0);
        }
        zipfile.readEntry();
      });
      zipfile.on('error', reject);
      zipfile.on('end', () => resolve({ entries, count, uncompressedBytes }));
    });
  });
}

function hasEntry(entries, expected) {
  return entries.has(expected) || [...entries].some((e) => e.endsWith('/' + expected));
}

function assertAsarEntry(asarFiles, expected) {
  const wanted = expected.replace(/\\/g, '/');
  const ok = asarFiles.some((f) => {
    const n = f.replace(/^\//, '').replace(/\\/g, '/');
    return n === wanted || n.endsWith('/' + wanted);
  });
  if (!ok) fail('app.asar is missing required shell file', [wanted]);
}

async function main() {
  assertFile(asarPath, 'resources/app.asar');

  let pkgMain = 'main.js';
  try {
    const raw = extractFile(asarPath, 'package.json');
    pkgMain = JSON.parse(raw.toString('utf8')).main || pkgMain;
  } catch (e) {
    fail('cannot read package.json inside app.asar', [e.message]);
  }

  const asarFiles = listPackage(asarPath);
  const norm = (f) => f.replace(/^\//, '').replace(/\\/g, '/');
  const leakedMapsInAsar = asarFiles.map(norm).filter((f) => f.toLowerCase().endsWith('.map'));
  if (leakedMapsInAsar.length) {
    fail('app.asar contains source maps', leakedMapsInAsar.slice(0, 20));
  }

  const base = path.basename(pkgMain.replace(/\\/g, '/'));
  const hasMain = asarFiles.some((f) => {
    const n = norm(f);
    return n === pkgMain.replace(/\\/g, '/') || n.endsWith('/' + base) || n === base;
  });
  if (!hasMain) {
    fail('main entry is not inside app.asar', [`main=${pkgMain}`, `asar files=${asarFiles.length}`]);
  }
  for (const required of [
    'package.json',
    'preload.js',
    'install-packaged.cjs',
    'mumu-detect.cjs',
    'release-update.cjs',
    'renderer/loading.html',
    'renderer/installer.html',
    'node_modules/tree-kill/index.js',
    'node_modules/yauzl/index.js',
    'node_modules/buffer-crc32/index.js',
    'node_modules/pend/index.js',
  ]) {
    assertAsarEntry(asarFiles, required);
  }

  const leakedMapsUnpacked = walkFiles(unpacked)
    .filter((f) => f.toLowerCase().endsWith('.map'))
    .map((f) => rel(unpacked, f));
  if (leakedMapsUnpacked.length) {
    fail('win-unpacked contains source maps', leakedMapsUnpacked.slice(0, 20));
  }

  const dataRoot = path.join(unpacked, 'data');
  validateDataRoot(dataRoot);
  assertDir(path.join(unpacked, 'license'), 'license');

  const backendZipCandidates = [
    path.join(unpacked, 'backend.zip'),
    path.join(unpacked, 'resources', 'backend.zip'),
  ];
  const backendZip = backendZipCandidates.find((p) => fs.existsSync(p));
  if (!backendZip) {
    fail('missing backend.zip', backendZipCandidates);
  }

  const zipInfo = await inspectZip(backendZip);
  const requiredBackendEntries = [
    'autoscriptor-engine.exe',
    'msvcp140.dll',
    'vcruntime140.dll',
    'vcruntime140_1.dll',
    'concrt140.dll',
    'vcomp140.dll',
    'services/webui/static/index.html',
    'services/webui/vendor/vue.global.js',
    'services/webui/vendor/element-plus.full.js',
    'encodings/__init__.py',
    'encodings/aliases.py',
    'encodings/utf_8.py',
    'pypinyin/pinyin_dict.json',
    'pypinyin/phrases_dict.json',
  ];
  const missingBackendEntries = requiredBackendEntries.filter((entry) => !hasEntry(zipInfo.entries, entry));
  if (!hasEntry(zipInfo.entries, 'wave.py') && !hasEntry(zipInfo.entries, 'wave.pyc')) {
    missingBackendEntries.push('wave.py or wave.pyc');
  }
  if (missingBackendEntries.length) {
    fail('backend.zip is missing required runtime files', missingBackendEntries);
  }

  const leakedMapsInZip = [...zipInfo.entries].filter((e) => e.toLowerCase().endsWith('.map'));
  if (leakedMapsInZip.length) {
    fail('backend.zip contains source maps', leakedMapsInZip.slice(0, 20));
  }

  note(`OK ${unpacked}`);
  note(`main=${pkgMain} asar_files=${asarFiles.length}`);
  note(`data=${dataRoot}`);
  note(`backend.zip=${backendZip} files=${zipInfo.count} uncompressed=${zipInfo.uncompressedBytes}`);
}

main().catch((e) => {
  fail('failed reading packaged artifact', [e && e.stack ? e.stack : String(e)]);
});
