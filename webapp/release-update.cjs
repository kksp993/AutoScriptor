'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const yauzl = require('yauzl');

const UPDATE_FORMAT = 'autoscriptor_update_v1';
const MANIFEST_NAMES = ['update_manifest.json', 'autoscriptor_update.json'];
const ENGINE_PATH = 'backend/autoscriptor-engine.exe';

function stamp() {
  return new Date().toISOString().replace(/[:.]/g, '-');
}

function sleepMs(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function sha256Buffer(buf) {
  return crypto.createHash('sha256').update(buf).digest('hex');
}

function sha256FileSync(filePath, chunkSize = 1024 * 1024) {
  const h = crypto.createHash('sha256');
  const fd = fs.openSync(filePath, 'r');
  const buf = Buffer.allocUnsafe(chunkSize);
  try {
    while (true) {
      const n = fs.readSync(fd, buf, 0, buf.length, null);
      if (!n) break;
      h.update(buf.subarray(0, n));
    }
  } finally {
    fs.closeSync(fd);
  }
  return h.digest('hex');
}

function normalizeRel(raw) {
  const rel = String(raw || '').replace(/\\/g, '/').trim().replace(/^\/+/, '');
  if (!rel || rel.includes('\0') || rel.split('/').includes('..') || path.isAbsolute(rel)) {
    throw new Error('非法更新路径: ' + raw);
  }
  if (/^[a-zA-Z]:\//.test(rel)) {
    throw new Error('非法更新路径: ' + raw);
  }
  return rel;
}

function safeJoin(root, relRaw) {
  const rel = normalizeRel(relRaw);
  const rootAbs = path.resolve(root);
  const target = path.resolve(rootAbs, ...rel.split('/'));
  const back = path.relative(rootAbs, target);
  if (!back || back.startsWith('..') || path.isAbsolute(back)) {
    throw new Error('更新路径越界: ' + relRaw);
  }
  return target;
}

function isProtectedUpdatePath(relRaw) {
  const n = normalizeRel(relRaw).toLowerCase();
  if (n === 'data/config.json' || n === 'config.json') return true;
  return (
    n.startsWith('data/accounts/')
    || n.startsWith('data/custom_task/')
    || n.startsWith('data/battle_character/')
    || n.startsWith('data/logs/')
    || n.startsWith('accounts/')
    || n.startsWith('custom_task/')
    || n.startsWith('battle_character/')
    || n.startsWith('logs/')
    || n.startsWith('.autoscriptor/')
  );
}

function parseVersion(v) {
  const m = String(v || '').trim().match(/^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$/);
  if (!m) return null;
  return {
    major: Number(m[1]),
    minor: Number(m[2]),
    patch: Number(m[3]),
    line: `${Number(m[1])}.${Number(m[2])}`,
    text: `${Number(m[1])}.${Number(m[2])}.${Number(m[3])}`,
  };
}

function readJsonIfExists(filePath) {
  const result = readJsonObjectIfExists(filePath);
  return result.ok ? result.data : null;
}

function readJsonObjectIfExists(filePath) {
  const result = {
    exists: false,
    ok: false,
    data: null,
    error: '',
  };
  try {
    if (!fs.existsSync(filePath)) return result;
    result.exists = true;
    let text = fs.readFileSync(filePath, 'utf8');
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    const data = JSON.parse(text);
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      result.error = 'JSON is not an object';
      return result;
    }
    result.ok = true;
    result.data = data;
  } catch (e) {
    result.error = e && e.message ? e.message : String(e);
  }
  return result;
}

function resolveCurrentVersion(opts) {
  const explicit = String((opts && opts.currentVersion) || '').trim();
  if (explicit) return explicit;
  const installRoot = String((opts && opts.installRoot) || '').trim();
  if (installRoot) {
    const vfile = path.join(installRoot, '.autoscriptor', 'release_version.json');
    const j = readJsonIfExists(vfile);
    if (j && typeof j.version === 'string' && j.version.trim()) return j.version.trim();
  }
  const userDataPath = String((opts && opts.userDataPath) || '').trim();
  if (userDataPath) {
    const j = readJsonIfExists(path.join(userDataPath, 'install.json'));
    if (j && typeof j.version === 'string' && j.version.trim()) return j.version.trim();
  }
  return '';
}

function resolveRuntimeDataRoot(installRoot, userDataPath) {
  const userData = String(userDataPath || '').trim();
  if (userData) {
    const marker = readJsonIfExists(path.join(userData, 'install.json'));
    if (marker && typeof marker.dataRoot === 'string' && marker.dataRoot.trim()) {
      return path.resolve(marker.dataRoot);
    }
  }
  return path.join(path.resolve(installRoot), 'data');
}

function addCheck(report, id, ok, message, detail) {
  report.checks.push({ id, ok, message, ...(detail ? { detail } : {}) });
  if (ok === false) report.errors.push(message);
}

function finishReport(report) {
  report.ok = report.errors.length === 0 && !report.checks.some((c) => c.ok === false);
  return report;
}

function openZipWithEntryMap(zipPath) {
  return new Promise((resolve, reject) => {
    yauzl.open(zipPath, { lazyEntries: false, autoClose: false }, (err, zipfile) => {
      if (err) return reject(err);
      const map = new Map();
      zipfile.on('entry', (entry) => {
        if (!/\/$/.test(entry.fileName)) {
          const n = entry.fileName.replace(/\\/g, '/').replace(/^\/+/, '');
          map.set(n, entry);
        }
      });
      zipfile.on('end', () => resolve({ zipfile, map }));
      zipfile.on('error', reject);
    });
  });
}

function readZipEntryBuffer(zipfile, entry) {
  return new Promise((resolve, reject) => {
    zipfile.openReadStream(entry, (err, rs) => {
      if (err) return reject(err);
      const chunks = [];
      rs.on('data', (c) => chunks.push(c));
      rs.on('error', reject);
      rs.on('end', () => resolve(Buffer.concat(chunks)));
    });
  });
}

function extractZipEntryToPath(zipfile, entry, destPath) {
  return new Promise((resolve, reject) => {
    fs.mkdirSync(path.dirname(destPath), { recursive: true });
    const tmp = `${destPath}.tmp.${process.pid}`;
    zipfile.openReadStream(entry, (err, rs) => {
      if (err) return reject(err);
      const ws = fs.createWriteStream(tmp);
      rs.on('error', reject);
      ws.on('error', reject);
      ws.on('close', () => resolve(tmp));
      rs.pipe(ws);
    });
  }).then((tmp) => {
    if (fs.existsSync(destPath)) fs.rmSync(destPath, { force: true });
    fs.renameSync(tmp, destPath);
    return destPath;
  });
}

function findManifestEntry(map) {
  for (const name of MANIFEST_NAMES) {
    const entry = map.get(name);
    if (entry) return { name, entry };
  }
  return null;
}

function emptyReport(opts) {
  return {
    kind: 'local-release-update',
    ok: false,
    installRoot: path.resolve(String((opts && opts.installRoot) || '.')),
    packagePath: String((opts && opts.packagePath) || ''),
    currentVersion: '',
    targetVersion: '',
    compatLine: '',
    manifestName: '',
    checks: [],
    warnings: [],
    errors: [],
    plan: {
      replace: 0,
      add: 0,
      skip: 0,
      mkdir: 0,
      copyIfMissing: 0,
      configDefaults: { willWrite: false, missingKeys: [] },
      requiresBackendStop: false,
      files: [],
      actions: [],
    },
  };
}

function assertHexSha256(value, label) {
  if (!/^[0-9a-fA-F]{64}$/.test(String(value || ''))) {
    throw new Error(`${label} 必须是 64 位 SHA-256`);
  }
}

function normalizeFileOp(op, kind) {
  if (!op || typeof op !== 'object') throw new Error(`${kind} 条目必须是对象`);
  const rel = normalizeRel(op.path);
  const entry = normalizeRel(op.entry || op.path);
  assertHexSha256(op.sha256, `${kind} ${rel}`);
  if (isProtectedUpdatePath(rel)) {
    throw new Error(`更新包试图写入受保护用户数据路径: ${rel}`);
  }
  return { path: rel, entry, sha256: String(op.sha256).toLowerCase(), kind };
}

function configMissingKeys(current, defaults, prefix = '') {
  const missing = [];
  if (!defaults || typeof defaults !== 'object' || Array.isArray(defaults)) return missing;
  const cur = current && typeof current === 'object' && !Array.isArray(current) ? current : {};
  for (const [key, value] of Object.entries(defaults)) {
    const p = prefix ? `${prefix}.${key}` : key;
    if (!(key in cur)) {
      missing.push(p);
    } else if (
      value && typeof value === 'object' && !Array.isArray(value)
      && cur[key] && typeof cur[key] === 'object' && !Array.isArray(cur[key])
    ) {
      missing.push(...configMissingKeys(cur[key], value, p));
    }
  }
  return missing;
}

function mergeMissing(current, defaults) {
  if (!defaults || typeof defaults !== 'object' || Array.isArray(defaults)) return false;
  let changed = false;
  for (const [key, value] of Object.entries(defaults)) {
    if (!(key in current)) {
      current[key] = value;
      changed = true;
    } else if (
      value && typeof value === 'object' && !Array.isArray(value)
      && current[key] && typeof current[key] === 'object' && !Array.isArray(current[key])
    ) {
      changed = mergeMissing(current[key], value) || changed;
    }
  }
  return changed;
}

async function inspectUpdatePackage(opts) {
  const report = emptyReport(opts || {});
  const installRoot = String((opts && opts.installRoot) || '').trim();
  const packagePath = String((opts && opts.packagePath) || '').trim();
  let zipfile = null;

  try {
    if (!installRoot) {
      addCheck(report, 'installRoot', false, '未提供安装目录');
      return finishReport(report);
    }
    report.installRoot = path.resolve(installRoot);
    if (!fs.existsSync(report.installRoot) || !fs.statSync(report.installRoot).isDirectory()) {
      addCheck(report, 'installRoot', false, '安装目录不存在: ' + report.installRoot);
      return finishReport(report);
    }
    report.dataRoot = resolveRuntimeDataRoot(report.installRoot, opts && opts.userDataPath);
    addCheck(report, 'installRoot', true, '安装目录存在');

    if (!packagePath || !fs.existsSync(packagePath)) {
      addCheck(report, 'package', false, '更新包不存在: ' + (packagePath || ''));
      return finishReport(report);
    }
    report.packagePath = path.resolve(packagePath);
    addCheck(report, 'package', true, '更新包可读取');

    const opened = await openZipWithEntryMap(report.packagePath);
    zipfile = opened.zipfile;
    const map = opened.map;
    const manifestEntry = findManifestEntry(map);
    if (!manifestEntry) {
      addCheck(report, 'manifest', false, '更新包缺少 update_manifest.json');
      return finishReport(report);
    }
    report.manifestName = manifestEntry.name;
    const manifestRaw = await readZipEntryBuffer(zipfile, manifestEntry.entry);
    const manifest = JSON.parse(manifestRaw.toString('utf8'));
    if (!manifest || manifest.format !== UPDATE_FORMAT) {
      addCheck(report, 'manifest', false, `不支持的更新包格式（需要 ${UPDATE_FORMAT}）`);
      return finishReport(report);
    }
    addCheck(report, 'manifest', true, '更新清单格式正确');

    const currentRaw = resolveCurrentVersion(opts || {});
    const current = parseVersion(currentRaw);
    const target = parseVersion(manifest.target_version);
    const base = parseVersion(manifest.base_version);
    const compatLine = String(manifest.compat_line || (target && target.line) || '').trim();
    report.currentVersion = currentRaw || '';
    report.targetVersion = target ? target.text : String(manifest.target_version || '');
    report.compatLine = compatLine;

    if (!current) {
      addCheck(report, 'currentVersion', false, '无法识别当前安装版本，不能应用小版本更新');
    } else {
      addCheck(report, 'currentVersion', true, '当前版本: ' + current.text);
    }
    if (!target) {
      addCheck(report, 'targetVersion', false, '更新包 target_version 非法');
    } else {
      addCheck(report, 'targetVersion', true, '目标版本: ' + target.text);
    }
    if (target && compatLine !== target.line) {
      addCheck(report, 'compatLine', false, `compat_line 与 target_version 不一致: ${compatLine} != ${target.line}`);
    } else if (current && compatLine !== current.line) {
      addCheck(report, 'compatLine', false, `当前版本 ${current.text} 不在更新包兼容线 ${compatLine}.x 内，请使用完整安装包`);
    } else if (base && base.line !== compatLine) {
      addCheck(report, 'baseVersion', false, `base_version ${base.text} 不在兼容线 ${compatLine}.x 内`);
    } else if (current && target && current.patch > target.patch) {
      addCheck(report, 'targetVersion', false, `目标版本 ${target.text} 低于当前版本 ${current.text}，拒绝降级`);
    } else {
      addCheck(report, 'compatLine', true, `兼容线 ${compatLine}.x，可跳版本应用`);
    }

    const replace = Array.isArray(manifest.replace) ? manifest.replace.map((op) => normalizeFileOp(op, 'replace')) : [];
    const copyIfMissing = Array.isArray(manifest.copy_if_missing)
      ? manifest.copy_if_missing.map((op) => normalizeFileOp(op, 'copy_if_missing'))
      : [];
    const mkdir = Array.isArray(manifest.mkdir) ? manifest.mkdir.map((p) => normalizeRel(p)) : [];
    for (const rel of mkdir) {
      if (isProtectedUpdatePath(rel)) throw new Error(`更新包试图创建受保护用户数据路径: ${rel}`);
      safeJoin(report.installRoot, rel);
      if (!fs.existsSync(safeJoin(report.installRoot, rel))) report.plan.mkdir += 1;
    }

    for (const op of [...replace, ...copyIfMissing]) {
      const zipEntry = map.get(op.entry);
      if (!zipEntry) {
        addCheck(report, 'payload', false, `更新包缺少文件: ${op.entry}`);
        continue;
      }
      const data = await readZipEntryBuffer(zipfile, zipEntry);
      const got = sha256Buffer(data);
      if (got !== op.sha256) {
        addCheck(report, 'payloadSha256', false, `更新包文件校验失败: ${op.entry}`);
        continue;
      }
      const targetPath = safeJoin(report.installRoot, op.path);
      const exists = fs.existsSync(targetPath);
      const same = exists && fs.statSync(targetPath).isFile() && sha256FileSync(targetPath) === op.sha256;
      if (op.path.toLowerCase() === ENGINE_PATH) report.plan.requiresBackendStop = true;
      if (op.kind === 'copy_if_missing' && exists) {
        report.plan.skip += 1;
      } else if (same) {
        report.plan.skip += 1;
      } else if (exists) {
        report.plan.replace += 1;
      } else {
        report.plan.add += 1;
        if (op.kind === 'copy_if_missing') report.plan.copyIfMissing += 1;
      }
      report.plan.files.push({
        action: op.kind,
        path: op.path,
        entry: op.entry,
        exists,
        same,
      });
    }

    const configDefaults = manifest.config_defaults;
    if (configDefaults && typeof configDefaults === 'object' && !Array.isArray(configDefaults)) {
      const cfgPath = path.join(report.dataRoot, 'config.json');
      const cfgRead = readJsonObjectIfExists(cfgPath);
      if (cfgRead.exists && !cfgRead.ok) {
        addCheck(
          report,
          'configDefaults',
          false,
          `data/config.json is invalid; refusing to merge config_defaults: ${cfgRead.error}`,
        );
      } else {
        const cfg = cfgRead.ok ? cfgRead.data : {};
        const missing = configMissingKeys(cfg, configDefaults);
        report.plan.configDefaults = { willWrite: missing.length > 0, missingKeys: missing };
      }
    }

    const parentDirs = new Set();
    for (const f of report.plan.files) parentDirs.add(path.dirname(safeJoin(report.installRoot, f.path)));
    for (const rel of mkdir) parentDirs.add(safeJoin(report.installRoot, rel));
    for (const dir of parentDirs) {
      let probeDir = dir;
      while (!fs.existsSync(probeDir) && path.dirname(probeDir) !== probeDir) {
        probeDir = path.dirname(probeDir);
      }
      try {
        if (fs.existsSync(probeDir)) fs.accessSync(probeDir, fs.constants.W_OK);
      } catch (_) {
        report.warnings.push('可能没有写权限: ' + probeDir);
      }
    }

    report.plan.actions.push(
      '校验更新包 manifest、版本线与所有 payload SHA-256',
      report.plan.requiresBackendStop ? '停止当前 backend 后替换 autoscriptor-engine.exe' : '替换/补齐清单中的文件',
      '写入前备份旧文件，失败时回滚',
      '只补齐 config_defaults 中缺失配置项，不覆盖用户已有值',
    );
  } catch (e) {
    report.errors.push(e && e.message ? e.message : String(e));
  } finally {
    try {
      if (zipfile) zipfile.close();
    } catch (_) {}
  }
  return finishReport(report);
}

async function moveWithRetry(src, dest, label) {
  let lastErr = null;
  for (let i = 0; i < 8; i += 1) {
    try {
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      fs.renameSync(src, dest);
      return;
    } catch (e) {
      lastErr = e;
      await sleepMs(250 + i * 250);
    }
  }
  throw new Error(`${label || '文件'}移动失败: ${lastErr && lastErr.message ? lastErr.message : lastErr}`);
}

async function applyLocalReleaseUpdate(opts) {
  const dry = await inspectUpdatePackage(opts);
  if (!dry.ok) {
    throw new Error('更新包预检失败: ' + dry.errors.join('; '));
  }

  const installRoot = dry.installRoot;
  const dataRoot = dry.dataRoot || resolveRuntimeDataRoot(installRoot, opts && opts.userDataPath);
  const packagePath = dry.packagePath;
  const keepBackup = (opts && opts.keepBackup) !== false;
  const send = opts && typeof opts.send === 'function' ? opts.send : () => {};
  const stagingDir = path.join(installRoot, `.update.staging.${stamp()}.${process.pid}`);
  const backupDir = path.join(installRoot, `.update-backup.${stamp()}.${process.pid}`);
  const applied = [];
  let zipfile = null;

  const rollback = async () => {
    for (let i = applied.length - 1; i >= 0; i -= 1) {
      const item = applied[i];
      try {
        if (fs.existsSync(item.target)) fs.rmSync(item.target, { force: true, recursive: true });
        if (item.backup && fs.existsSync(item.backup)) {
          fs.mkdirSync(path.dirname(item.target), { recursive: true });
          fs.renameSync(item.backup, item.target);
        }
      } catch (_) {}
    }
  };

  try {
    send({ type: 'progress', percent: 5, message: '读取更新包…' });
    const opened = await openZipWithEntryMap(packagePath);
    zipfile = opened.zipfile;
    const map = opened.map;
    const manifestEntry = findManifestEntry(map);
    const manifest = JSON.parse((await readZipEntryBuffer(zipfile, manifestEntry.entry)).toString('utf8'));
    const replace = Array.isArray(manifest.replace) ? manifest.replace.map((op) => normalizeFileOp(op, 'replace')) : [];
    const copyIfMissing = Array.isArray(manifest.copy_if_missing)
      ? manifest.copy_if_missing.map((op) => normalizeFileOp(op, 'copy_if_missing'))
      : [];
    const mkdir = Array.isArray(manifest.mkdir) ? manifest.mkdir.map((p) => normalizeRel(p)) : [];
    const fileOps = [...replace, ...copyIfMissing];
    fs.mkdirSync(stagingDir, { recursive: true });
    fs.mkdirSync(backupDir, { recursive: true });

    for (const rel of mkdir) {
      fs.mkdirSync(safeJoin(installRoot, rel), { recursive: true });
    }

    let idx = 0;
    for (const op of fileOps) {
      idx += 1;
      const target = safeJoin(installRoot, op.path);
      if (op.kind === 'copy_if_missing' && fs.existsSync(target)) {
        send({ type: 'log', message: `[更新] 已存在，跳过 ${op.path}` });
        continue;
      }
      if (fs.existsSync(target) && fs.statSync(target).isFile() && sha256FileSync(target) === op.sha256) {
        send({ type: 'log', message: `[更新] 已是目标版本，跳过 ${op.path}` });
        continue;
      }

      const entry = map.get(op.entry);
      const staged = safeJoin(stagingDir, op.entry);
      await extractZipEntryToPath(zipfile, entry, staged);
      const stagedSha = sha256FileSync(staged);
      if (stagedSha !== op.sha256) {
        throw new Error(`staging 校验失败: ${op.path}`);
      }

      let backup = null;
      if (fs.existsSync(target)) {
        backup = safeJoin(backupDir, op.path);
        await moveWithRetry(target, backup, '备份旧文件');
      }
      const appliedItem = { target, backup };
      if (backup) applied.push(appliedItem);
      await moveWithRetry(staged, target, '写入新文件');
      const got = sha256FileSync(target);
      if (got !== op.sha256) {
        throw new Error(`目标文件校验失败: ${op.path}`);
      }
      if (!backup) applied.push(appliedItem);
      send({
        type: 'progress',
        percent: Math.min(90, 10 + Math.floor((80 * idx) / Math.max(1, fileOps.length))),
        message: `已更新 ${idx}/${fileOps.length}`,
      });
      send({ type: 'log', message: `[更新] 已写入 ${op.path}` });
    }

    if (manifest.config_defaults && typeof manifest.config_defaults === 'object' && !Array.isArray(manifest.config_defaults)) {
      const cfgPath = path.join(dataRoot, 'config.json');
      const cfgRead = readJsonObjectIfExists(cfgPath);
      if (cfgRead.exists && !cfgRead.ok) {
        throw new Error(`data/config.json is invalid; refusing to merge config_defaults: ${cfgRead.error}`);
      }
      const cfg = cfgRead.ok ? cfgRead.data : {};
      const changed = mergeMissing(cfg, manifest.config_defaults);
      if (changed) {
        const cfgBackup = safeJoin(backupDir, 'data/config.json');
        if (fs.existsSync(cfgPath)) {
          fs.mkdirSync(path.dirname(cfgBackup), { recursive: true });
          fs.copyFileSync(cfgPath, cfgBackup);
        }
        fs.mkdirSync(path.dirname(cfgPath), { recursive: true });
        fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 2), 'utf8');
      }
    }

    const versionDir = path.join(installRoot, '.autoscriptor');
    fs.mkdirSync(versionDir, { recursive: true });
    fs.writeFileSync(
      path.join(versionDir, 'release_version.json'),
      JSON.stringify({ version: dry.targetVersion, updated_at: new Date().toISOString() }, null, 2),
      'utf8',
    );
    const userDataPath = String((opts && opts.userDataPath) || '').trim();
    if (userDataPath) {
      const markerPath = path.join(userDataPath, 'install.json');
      const marker = readJsonIfExists(markerPath) || {};
      marker.installRoot = installRoot;
      marker.dataRoot = dataRoot;
      marker.version = dry.targetVersion;
      fs.mkdirSync(userDataPath, { recursive: true });
      fs.writeFileSync(markerPath, JSON.stringify(marker, null, 2), 'utf8');
    }

    try {
      fs.rmSync(stagingDir, { recursive: true, force: true });
    } catch (_) {}
    if (!keepBackup) {
      try {
        fs.rmSync(backupDir, { recursive: true, force: true });
      } catch (_) {}
    }
    send({ type: 'progress', percent: 100, message: '小版本更新完成' });
    send({ type: 'complete' });
    return { ok: true, report: dry, backupDir: keepBackup ? backupDir : '' };
  } catch (e) {
    await rollback();
    try {
      fs.rmSync(stagingDir, { recursive: true, force: true });
    } catch (_) {}
    throw e;
  } finally {
    try {
      if (zipfile) zipfile.close();
    } catch (_) {}
  }
}

module.exports = {
  UPDATE_FORMAT,
  ENGINE_PATH,
  inspectUpdatePackage,
  dryRunLocalReleaseUpdate: inspectUpdatePackage,
  applyLocalReleaseUpdate,
  __test: {
    normalizeRel,
    safeJoin,
    isProtectedUpdatePath,
    parseVersion,
    configMissingKeys,
    mergeMissing,
    sha256Buffer,
    sha256FileSync,
  },
};
