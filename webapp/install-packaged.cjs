'use strict';

/**
 * 发行版（薄包）：将 resources/backend.zip 解压到用户选择的安装目录，将可写 data 放到 Electron userData，写 install.json，注册卸载。
 *
 * 增量包（backend_incremental.zip）：由 scripts/release/release_backend_incremental.py 对比旧版 gui.dist / backend.zip
 * 与新版生成；applyBackendIncremental 在已有 backend/ 上校验 SHA-256 后覆盖，无需全量删除解压。
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const yauzl = require('yauzl');
const { spawn, spawnSync } = require('child_process');

function safeJoin(dest, name) {
  const n = name.replace(/\\/g, '/');
  if (n.includes('..') || path.isAbsolute(n)) {
    throw new Error('非法 zip 路径: ' + name);
  }
  return path.join(dest, ...n.split('/'));
}

function resolveRuntimeDataRoot(installRoot, userDataPath) {
  const userData = String(userDataPath || '').trim();
  if (userData) return path.join(path.resolve(userData), 'data');
  return path.join(path.resolve(installRoot), 'data');
}

function countZipFiles(zipPath) {
  return new Promise((resolve, reject) => {
    yauzl.open(zipPath, { lazyEntries: false }, (err, zipfile) => {
      if (err) return reject(err);
      let n = 0;
      zipfile.on('entry', (e) => {
        if (!e.fileName.endsWith('/')) n += 1;
      });
      zipfile.on('end', () => resolve(n));
      zipfile.on('error', reject);
    });
  });
}

function extractZip(zipPath, destDir, { onFile }) {
  return new Promise((resolve, reject) => {
    yauzl.open(zipPath, { lazyEntries: true }, (err, zipfile) => {
      if (err) return reject(err);
      let done = 0;
      zipfile.readEntry();
      zipfile.on('entry', (entry) => {
        if (/\/$/.test(entry.fileName)) {
          try {
            fs.mkdirSync(safeJoin(destDir, entry.fileName), { recursive: true });
          } catch (e) {
            return reject(e);
          }
          zipfile.readEntry();
          return;
        }
        zipfile.openReadStream(entry, (err2, readStream) => {
          if (err2) return reject(err2);
          let outPath;
          try {
            outPath = safeJoin(destDir, entry.fileName);
          } catch (e) {
            return reject(e);
          }
          fs.mkdirSync(path.dirname(outPath), { recursive: true });
          const ws = fs.createWriteStream(outPath);
          readStream.on('error', reject);
          ws.on('error', reject);
          ws.on('close', () => {
            done += 1;
            if (onFile) onFile(done, entry.fileName);
            zipfile.readEntry();
          });
          readStream.pipe(ws);
        });
      });
      zipfile.on('end', () => resolve(done));
      zipfile.on('error', reject);
    });
  });
}

function resolveWindowsTarExe() {
  if (process.platform !== 'win32') return '';
  const candidates = [
    path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'tar.exe'),
    'tar.exe',
  ];
  for (const candidate of candidates) {
    const check = spawnSync(candidate, ['--version'], {
      windowsHide: true,
      stdio: 'ignore',
    });
    if (!check.error && check.status === 0) return candidate;
  }
  return '';
}

function extractZipWithNativeTar(zipPath, destDir, { send, total }) {
  const tarExe = resolveWindowsTarExe();
  if (!tarExe) return Promise.resolve({ attempted: false, ok: false });
  safeSend(send, {
    type: 'log',
    message: `[解压] 使用系统 tar.exe 加速解压（${total} 个文件），完成前进度会停留在此步骤…`,
  });
  safeSend(send, { type: 'progress', percent: 8, message: '系统解压中…' });

  return new Promise((resolve) => {
    const child = spawn(tarExe, ['-xf', zipPath, '-C', destDir], {
      windowsHide: true,
      stdio: ['ignore', 'ignore', 'pipe'],
    });
    let stderr = '';
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString('utf8');
      if (stderr.length > 4000) stderr = stderr.slice(-4000);
    });
    child.on('error', (e) => {
      safeSend(send, { type: 'log', message: `[解压] tar.exe 启动失败，回退 JS 解压：${e.message}` });
      resolve({ attempted: true, ok: false });
    });
    child.on('close', (code) => {
      if (code === 0) {
        safeSend(send, { type: 'progress', percent: 89, message: `系统解压完成（${total} 个文件）` });
        safeSend(send, { type: 'log', message: '[解压] tar.exe 解压完成' });
        resolve({ attempted: true, ok: true });
      } else {
        const msg = stderr.trim() ? `：${stderr.trim()}` : '';
        safeSend(send, { type: 'log', message: `[解压] tar.exe 解压失败，回退 JS 解压（exit=${code}${msg}）` });
        resolve({ attempted: true, ok: false });
      }
    });
  });
}

function writeUninstallPs1(installRoot, userDataInstallJson, dataRoot) {
  const rootResolved = path.resolve(installRoot);
  const rootJson = JSON.stringify(rootResolved);
  const markerJson = JSON.stringify(userDataInstallJson);
  const dataRootJson = JSON.stringify(dataRoot ? path.resolve(dataRoot) : '');

  const buildInner = (removeUserData) => [
    '$ErrorActionPreference = "Continue"',
    `$log = Join-Path $env:TEMP "ZaoBiUninstall-error.log"`,
    `$root = ${rootJson}`,
    `$dataRoot = ${dataRootJson}`,
    `$removeUserData = ${removeUserData ? '$true' : '$false'}`,
    'function Stop-UnderRoot {',
    '  try {',
    '    Get-CimInstance Win32_Process | Where-Object {',
    '      ($_.ProcessId -ne $PID) -and (',
    '        ($_.ExecutablePath -and (@("造笔.exe","AutoScriptor-Portable.exe","autoscriptor-engine.exe") -contains (Split-Path -Leaf $_.ExecutablePath))) -or',
    '        ($_.ExecutablePath -and ($_.ExecutablePath.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase))) -or',
    '        ($_.CommandLine -and ($_.CommandLine.IndexOf($root, [System.StringComparison]::OrdinalIgnoreCase) -ge 0))',
    '      )',
    '    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }',
    '  } catch { }',
    '}',
    'function Remove-AppFiles {',
    '  $items = @("backend","license","造笔.exe","AutoScriptor-Portable.exe","backend.zip","backend_incremental.zip","Uninstall.ps1","卸载造笔.bat","彻底卸载造笔.bat")',
    '  foreach ($item in $items) {',
    '    $p = Join-Path $root $item',
    '    if (Test-Path -LiteralPath $p) {',
    '      try { Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop } catch { $_ | Out-File -FilePath $log -Append -Encoding utf8 }',
    '    }',
    '  }',
    '  try {',
    '    if (Test-Path -LiteralPath $root) {',
    '      $left = @(Get-ChildItem -LiteralPath $root -Force -ErrorAction SilentlyContinue)',
    '      if ($left.Count -eq 0) { Remove-Item -LiteralPath $root -Force -ErrorAction SilentlyContinue }',
    '    }',
    '  } catch { }',
    '}',
    'Start-Sleep -Seconds 5',
    'foreach ($round in 1..12) {',
    '  if (-not (Test-Path -LiteralPath $root)) {',
    '    if ($removeUserData -and $dataRoot -and (Test-Path -LiteralPath $dataRoot)) {',
    '      try { Remove-Item -LiteralPath $dataRoot -Recurse -Force -ErrorAction Stop } catch { $_ | Out-File -FilePath $log -Append -Encoding utf8 }',
    '    }',
    '    exit 0',
    '  }',
    '  Stop-UnderRoot',
    '  Start-Sleep -Milliseconds (400 + $round * 150)',
    '  if ($removeUserData) {',
    '    if ($dataRoot -and ($dataRoot.IndexOf($root, [System.StringComparison]::OrdinalIgnoreCase) -ne 0) -and (Test-Path -LiteralPath $dataRoot)) {',
    '      try { Remove-Item -LiteralPath $dataRoot -Recurse -Force -ErrorAction Stop } catch { $_ | Out-File -FilePath $log -Append -Encoding utf8 }',
    '    }',
    '    try { Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction Stop } catch { $_ | Out-File -FilePath $log -Append -Encoding utf8 }',
    '    if (-not (Test-Path -LiteralPath $root)) { exit 0 }',
    '    try {',
    '      $q = [char]34',
    '      $a = "/c rd /s /q " + $q + $root + $q',
    '      Start-Process -FilePath $env:ComSpec -ArgumentList $a -Wait -NoNewWindow',
    '    } catch { $_ | Out-File -FilePath $log -Append -Encoding utf8 }',
    '    if (-not (Test-Path -LiteralPath $root)) { exit 0 }',
    '  } else {',
    '    Remove-AppFiles',
    '    exit 0',
    '  }',
    '  Start-Sleep -Seconds 2',
    '}',
    '("卸载后仍存在目录: " + $root) | Out-File -FilePath $log -Append -Encoding utf8',
    'exit 1',
  ].join('\r\n');
  const encodedKeepData = Buffer.from(buildInner(false), 'utf16le').toString('base64');
  const encodedRemoveAll = Buffer.from(buildInner(true), 'utf16le').toString('base64');

  const outer = [
    '# 造笔卸载：注册表/标记 → 结束占用进程 → 子进程延迟多轮删除安装目录',
    'param([switch]$RemoveUserData)',
    '$ErrorActionPreference = "Continue"',
    `$root = ${rootJson}`,
    `$marker = ${markerJson}`,
    '& reg.exe delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\AutoScriptorZao" /f 2>$null',
    'if (Test-Path -LiteralPath $marker) { Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue }',
    'try {',
    '  Get-CimInstance Win32_Process | Where-Object {',
    '    ($_.ProcessId -ne $PID) -and (',
    '      ($_.ExecutablePath -and (@("造笔.exe","AutoScriptor-Portable.exe","autoscriptor-engine.exe") -contains (Split-Path -Leaf $_.ExecutablePath))) -or',
    '      ($_.ExecutablePath -and ($_.ExecutablePath.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase))) -or',
    '      ($_.CommandLine -and ($_.CommandLine.IndexOf($root, [System.StringComparison]::OrdinalIgnoreCase) -ge 0))',
    '    )',
    '  } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }',
    '} catch { }',
    'Start-Sleep -Seconds 2',
    `$encKeepData = ${JSON.stringify(encodedKeepData)}`,
    `$encRemoveAll = ${JSON.stringify(encodedRemoveAll)}`,
    '$enc = if ($RemoveUserData) { $encRemoveAll } else { $encKeepData }',
    '$psExe = Join-Path $env:SystemRoot "System32\\WindowsPowerShell\\v1.0\\powershell.exe"',
    'Start-Process -FilePath $psExe -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-EncodedCommand",$enc -WindowStyle Hidden',
    'if ($RemoveUserData) {',
    '  Write-Host "已移除注册信息；安装目录正在后台彻底删除（多轮重试）。若仍有残留请查看 %TEMP%\\ZaoBiUninstall-error.log"',
    '} else {',
    '  Write-Host "已移除注册信息；程序文件正在后台删除，data 用户数据会保留。若仍有残留请查看 %TEMP%\\ZaoBiUninstall-error.log"',
    '}',
    'Start-Sleep -Seconds 2',
  ].join('\r\n');

  const ps1 = path.join(installRoot, 'Uninstall.ps1');
  fs.writeFileSync(ps1, '\ufeff' + outer, 'utf8');

  const bat = path.join(installRoot, '卸载造笔.bat');
  const batBody = `@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "${ps1.replace(/"/g, '\\"')}"
`;
  fs.writeFileSync(bat, batBody, 'utf8');

  const batAll = path.join(installRoot, '彻底卸载造笔.bat');
  const batAllBody = `@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "${ps1.replace(/"/g, '\\"')}" -RemoveUserData
`;
  fs.writeFileSync(batAll, batAllBody, 'utf8');
}

function sleepMs(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function sha256FileSync(filePath) {
  const h = crypto.createHash('sha256');
  const fd = fs.openSync(filePath, 'r');
  try {
    const buf = Buffer.alloc(256 * 1024);
    let n;
    while ((n = fs.readSync(fd, buf, 0, buf.length, null)) > 0) {
      h.update(buf.subarray(0, n));
    }
  } finally {
    fs.closeSync(fd);
  }
  return h.digest('hex');
}

function sha256Buffer(buf) {
  return crypto.createHash('sha256').update(buf).digest('hex');
}

function safeSend(send, data) {
  if (typeof send === 'function') send(data);
}

function createExtractProgressReporter(opts) {
  const {
    send,
    total,
    progressStart = 5,
    progressSpan = 84,
    progressMax = 89,
    logEveryFiles = 500,
    logMinIntervalMs = 1500,
    progressMinIntervalMs = 250,
  } = opts || {};

  const totalSafe = Math.max(Number(total) || 0, 1);
  let lastLogAt = 0;
  let lastLogDone = 0;
  let lastProgressAt = 0;
  let lastProgressPct = -1;

  return (done, name) => {
    const now = Date.now();
    const first = done === 1;
    const final = done >= totalSafe;
    const pct = Math.min(progressMax, progressStart + Math.floor((progressSpan * done) / totalSafe));

    if (
      first ||
      final ||
      pct !== lastProgressPct ||
      now - lastProgressAt >= progressMinIntervalMs
    ) {
      safeSend(send, { type: 'progress', percent: pct, message: `解压 ${done}/${total}` });
      lastProgressAt = now;
      lastProgressPct = pct;
    }

    if (
      first ||
      final ||
      done - lastLogDone >= logEveryFiles ||
      now - lastLogAt >= logMinIntervalMs
    ) {
      safeSend(send, { type: 'log', message: `[解压] ${done}/${total} ${name}` });
      lastLogAt = now;
      lastLogDone = done;
    }
  };
}

function stamp() {
  return new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14);
}

function formatBytes(n) {
  if (!Number.isFinite(n)) return 'unknown';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = n;
  let idx = 0;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx += 1;
  }
  return `${value.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`;
}

function looksLikeManagedInstallRoot(root) {
  if (!fs.existsSync(root)) return false;
  const markers = ['backend', 'Uninstall.ps1', '卸载造笔.bat', '造笔.exe'];
  return markers.some((name) => fs.existsSync(path.join(root, name)))
    || fs.existsSync(path.join(root, 'data', 'config.json'));
}

function validatePackagedInstallRoot(rootResolved) {
  const parent = path.dirname(rootResolved);
  if (!fs.existsSync(parent)) {
    return {
      ok: false,
      reason: `父目录不存在: ${parent}`,
      exists: false,
      managed: false,
      entryCount: 0,
      existingEntries: [],
    };
  }

  let exists = false;
  let managed = false;
  let existingEntries = [];
  try {
    exists = fs.existsSync(rootResolved);
    if (exists) {
      const st = fs.statSync(rootResolved);
      if (!st.isDirectory()) {
        return {
          ok: false,
          reason: '所选安装目录已被文件占用，请选择一个空目录',
          exists: true,
          managed: false,
          entryCount: 0,
          existingEntries: [],
        };
      }
      existingEntries = fs.readdirSync(rootResolved);
      managed = looksLikeManagedInstallRoot(rootResolved);
      if (existingEntries.length > 0 && !managed) {
        return {
          ok: false,
          reason: `目录不为空（含 ${existingEntries.length} 个项目）。请选择一个空目录，或先卸载旧版后重试。`,
          exists: true,
          managed: false,
          entryCount: existingEntries.length,
          existingEntries,
        };
      }
    }
    const probeDir = exists ? rootResolved : parent;
    fs.accessSync(probeDir, fs.constants.W_OK | fs.constants.X_OK);
  } catch (e) {
    return {
      ok: false,
      reason: `无法写入目标目录: ${e.message}`,
      exists,
      managed,
      entryCount: existingEntries.length,
      existingEntries,
    };
  }

  return {
    ok: true,
    reason: '',
    exists,
    managed,
    entryCount: existingEntries.length,
    existingEntries,
  };
}

function planPackagedDataMerge(dataSrc, dataDest) {
  const plan = {
    sourceExists: !!dataSrc && fs.existsSync(dataSrc),
    destinationExists: !!dataDest && fs.existsSync(dataDest),
    sourceFiles: 0,
    sourceBytes: 0,
    copiedFiles: 0,
    keptUserFiles: 0,
    newFiles: 0,
  };

  if (!plan.sourceExists) {
    return plan;
  }

  const walk = (srcDir) => {
    for (const entry of fs.readdirSync(srcDir, { withFileTypes: true })) {
      const src = path.join(srcDir, entry.name);
      const rel = path.relative(dataSrc, src);
      const dest = path.join(dataDest, rel);
      if (entry.isDirectory()) {
        walk(src);
        continue;
      }
      if (!entry.isFile()) continue;
      plan.sourceFiles += 1;
      plan.sourceBytes += fs.statSync(src).size;
      if (fs.existsSync(dest)) {
        if (shouldOverwritePackagedData(rel)) {
          plan.copiedFiles += 1;
        } else {
          plan.keptUserFiles += 1;
        }
      } else {
        plan.copiedFiles += 1;
        plan.newFiles += 1;
      }
    }
  };

  walk(dataSrc);
  return plan;
}

function readJsonObject(filePath) {
  const result = {
    exists: fs.existsSync(filePath),
    ok: false,
    path: filePath,
    data: null,
    error: '',
  };
  if (!result.exists) {
    result.error = 'missing';
    return result;
  }
  try {
    let text = fs.readFileSync(filePath, 'utf8');
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    const data = JSON.parse(text);
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      result.error = 'not a JSON object';
      return result;
    }
    result.ok = true;
    result.data = data;
  } catch (e) {
    result.error = e && e.message ? e.message : String(e);
  }
  return result;
}

function isPlainObject(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value));
}

function mergeMissingConfigDefaults(current, defaults, prefix = '', changes = []) {
  if (!isPlainObject(current) || !isPlainObject(defaults)) return current;
  for (const [key, defaultValue] of Object.entries(defaults)) {
    const p = prefix ? `${prefix}.${key}` : key;
    if (!(key in current)) {
      current[key] = cloneJson(defaultValue);
      changes.push(p);
      continue;
    }
    if (isPlainObject(current[key]) && isPlainObject(defaultValue)) {
      mergeMissingConfigDefaults(current[key], defaultValue, p, changes);
    }
  }
  return current;
}

function previewConfigDefaultMerge(defaults, current) {
  const changes = [];
  if (!isPlainObject(defaults) || !isPlainObject(current)) {
    return { merged: current, missingKeys: changes };
  }
  const merged = cloneJson(current);
  mergeMissingConfigDefaults(merged, defaults, '', changes);
  return { merged, missingKeys: changes };
}

function chooseConfigDefaults(sourceTemplate, sourceConfig) {
  if (sourceTemplate && sourceTemplate.ok && isPlainObject(sourceTemplate.data)) {
    return { path: sourceTemplate.path, data: sourceTemplate.data };
  }
  if (sourceConfig && sourceConfig.ok && isPlainObject(sourceConfig.data)) {
    return { path: sourceConfig.path, data: sourceConfig.data };
  }
  return { path: '', data: null };
}

function listFilesRecursive(root) {
  const out = [];
  if (!root || !fs.existsSync(root)) return out;
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(p);
      } else if (entry.isFile()) {
        out.push(p);
      }
    }
  };
  walk(root);
  return out;
}

function validateConfigShape(config, label, opts = {}) {
  const errors = [];
  const warnings = [];
  const allowAbsoluteAccountsDir = !!opts.allowAbsoluteAccountsDir;
  if (!config || typeof config !== 'object') {
    errors.push(`${label}: config is not a JSON object`);
    return { errors, warnings };
  }
  for (const key of ['app', 'emulator', 'ocr', 'deploy', 'accounts', 'current_account']) {
    if (!(key in config)) errors.push(`${label}: missing ${key}`);
  }
  if (!config.app || typeof config.app !== 'object') {
    errors.push(`${label}: app section must be an object`);
  } else if (config.app.name !== 'ZmxyOL') {
    errors.push(`${label}: app.name must be ZmxyOL`);
  } else if (!('app_to_start' in config.app)) {
    errors.push(`${label}: app.app_to_start is missing`);
  }
  if (!config.emulator || typeof config.emulator !== 'object') {
    errors.push(`${label}: emulator section must be an object`);
  } else {
    for (const key of ['index', 'adb_addr', 'mumu_folder', 'emu_path', 'adb_path']) {
      if (!(key in config.emulator)) errors.push(`${label}: emulator.${key} is missing`);
    }
  }
  if (!config.accounts || typeof config.accounts !== 'object') {
    errors.push(`${label}: accounts section must be an object`);
  } else {
    const accountsDir = String(config.accounts.dir || '').trim();
    if (accountsDir && path.isAbsolute(accountsDir) && !allowAbsoluteAccountsDir) {
      errors.push(`${label}: accounts.dir must not be an absolute path`);
    } else if (accountsDir && path.isAbsolute(accountsDir)) {
      warnings.push(`${label}: accounts.dir is an absolute external account directory`);
    }
  }
  if (!config.current_account || typeof config.current_account !== 'string') {
    errors.push(`${label}: current_account must be a non-empty string`);
  }
  const deploy = config.deploy || {};
  if (deploy.content_manifest_url && !/^https?:\/\//i.test(String(deploy.content_manifest_url))) {
    warnings.push(`${label}: deploy.content_manifest_url is not an http(s) URL`);
  }
  return { errors, warnings };
}

function inspectPackagedRuntimeData(dataSrc, dataDest, opts = {}) {
  const report = {
    source: dataSrc,
    destination: dataDest,
    effectiveConfigPath: '',
    effectiveConfigSource: '',
    errors: [],
    warnings: [],
    checks: {},
    mumuPreview: null,
    configDefaults: {
      source: '',
      target: '',
      missingKeys: [],
      willWrite: false,
    },
  };

  if (!dataSrc || !fs.existsSync(dataSrc) || !fs.statSync(dataSrc).isDirectory()) {
    report.errors.push('packaged data directory is missing');
    return report;
  }
  report.checks.dataDirectory = true;

  const sourceConfig = readJsonObject(path.join(dataSrc, 'config.json'));
  const sourceTemplate = readJsonObject(path.join(dataSrc, 'config template.json'));
  report.checks.sourceConfig = sourceConfig.ok;
  report.checks.sourceTemplate = sourceTemplate.ok;
  if (!sourceConfig.ok) report.errors.push(`packaged data/config.json invalid: ${sourceConfig.error}`);
  if (!sourceTemplate.ok) report.errors.push(`packaged data/config template.json invalid: ${sourceTemplate.error}`);
  if (sourceConfig.ok) {
    const cfgCheck = validateConfigShape(sourceConfig.data, 'packaged data/config.json');
    report.errors.push(...cfgCheck.errors);
    report.warnings.push(...cfgCheck.warnings);
  }
  if (sourceTemplate.ok) {
    const tplCheck = validateConfigShape(sourceTemplate.data, 'packaged data/config template.json');
    report.errors.push(...tplCheck.errors);
    report.warnings.push(...tplCheck.warnings);
  }

  const defaults = chooseConfigDefaults(sourceTemplate, sourceConfig);
  report.configDefaults.source = defaults.path;
  const existingConfigPath = path.join(dataDest, 'config.json');
  const hasExistingConfig = fs.existsSync(existingConfigPath);
  const effective = hasExistingConfig ? readJsonObject(existingConfigPath) : sourceConfig;
  report.effectiveConfigPath = effective.path;
  report.effectiveConfigSource = hasExistingConfig ? 'existing-user-data' : 'packaged-data';
  report.configDefaults.target = hasExistingConfig ? existingConfigPath : '';
  report.checks.effectiveConfig = effective.ok;
  if (!effective.ok) {
    report.errors.push(`effective data/config.json invalid: ${effective.error}`);
  } else {
    let effectiveData = effective.data;
    if (hasExistingConfig && defaults.data) {
      const mergePlan = previewConfigDefaultMerge(defaults.data, effective.data);
      effectiveData = mergePlan.merged;
      report.configDefaults.missingKeys = mergePlan.missingKeys;
      report.configDefaults.willWrite = mergePlan.missingKeys.length > 0;
      if (mergePlan.missingKeys.length) {
        report.warnings.push(
          `existing data/config.json will be supplemented from packaged template: ${mergePlan.missingKeys.slice(0, 8).join(', ')}`
        );
      }
    }
    const effCheck = validateConfigShape(effectiveData, 'effective data/config.json', {
      allowAbsoluteAccountsDir: hasExistingConfig,
    });
    report.errors.push(...effCheck.errors);
    report.warnings.push(...effCheck.warnings);
    if (opts.previewMumu !== false) {
      try {
        const { previewMumuConfig } = require('./mumu-detect.cjs');
        report.mumuPreview = previewMumuConfig(effectiveData, { probeAdb: false });
        if (report.mumuPreview.willNeedManualPaths) {
          report.warnings.push('MuMu/ADB paths are not fully resolved; installer will require path validation after install');
        }
      } catch (e) {
        report.warnings.push('MuMu preview failed: ' + (e && e.message ? e.message : String(e)));
      }
    }
  }

  const uiMapPath = path.join(dataSrc, 'assets', 'config', 'ui_map.csv');
  report.checks.uiMap = fs.existsSync(uiMapPath) && fs.statSync(uiMapPath).isFile();
  if (!report.checks.uiMap) {
    report.errors.push('packaged data/assets/config/ui_map.csv is missing');
  } else {
    const header = fs.readFileSync(uiMapPath, 'utf8').split(/\r?\n/, 1)[0].split(',');
    for (const col of ['key', 'text', 'left', 'top', 'width', 'height', 'img']) {
      if (!header.includes(col)) report.errors.push(`ui_map.csv missing column: ${col}`);
    }
  }

  const heroPath = path.join(dataSrc, 'battle_character', 'hero.py');
  report.checks.battleCharacter = fs.existsSync(heroPath) && fs.statSync(heroPath).isFile();
  if (!report.checks.battleCharacter) {
    report.errors.push('packaged data/battle_character/hero.py is missing');
  }

  const accountJson = listFilesRecursive(path.join(dataSrc, 'accounts'))
    .filter((f) => f.toLowerCase().endsWith('.json'))
    .map((f) => path.relative(dataSrc, f).replace(/\\/g, '/'));
  report.checks.noAccountJsonLeak = accountJson.length === 0;
  if (accountJson.length) {
    report.errors.push('packaged data/accounts contains user JSON files: ' + accountJson.slice(0, 5).join(', '));
  }

  const bytecode = listFilesRecursive(dataSrc)
    .filter((f) => /\.(pyc|pyo)$/i.test(f) || f.toLowerCase().includes(`${path.sep}__pycache__${path.sep}`))
    .map((f) => path.relative(dataSrc, f).replace(/\\/g, '/'));
  report.checks.noPythonBytecode = bytecode.length === 0;
  if (bytecode.length) {
    report.errors.push('packaged data contains Python bytecode/cache files: ' + bytecode.slice(0, 5).join(', '));
  }

  report.checks.customTaskDir = fs.existsSync(path.join(dataSrc, 'custom_task'));
  if (!report.checks.customTaskDir) {
    report.warnings.push('packaged data/custom_task directory is missing; user scripts can still be created later');
  }

  return report;
}

function resolveBackendZipPath({ zipPath, exeDir, resourcesPath }) {
  const candidates = [];
  if (zipPath) candidates.push(zipPath);
  if (exeDir) candidates.push(path.join(exeDir, 'backend.zip'));
  if (resourcesPath) candidates.push(path.join(resourcesPath, 'backend.zip'));
  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  return candidates[0] || '';
}

function dirSizeSync(root) {
  if (!fs.existsSync(root)) return 0;
  const st = fs.statSync(root);
  if (!st.isDirectory()) return st.size;
  let total = 0;
  for (const name of fs.readdirSync(root)) {
    total += dirSizeSync(path.join(root, name));
  }
  return total;
}

function getFreeBytes(targetDir) {
  if (typeof fs.statfsSync === 'function') {
    try {
      const root = path.parse(path.resolve(targetDir)).root || targetDir;
      const st = fs.statfsSync(root);
      return Number(st.bavail || st.bfree) * Number(st.bsize);
    } catch (_) {}
  }
  if (process.platform === 'win32') {
    try {
      const { execFileSync } = require('child_process');
      const drive = path.parse(path.resolve(targetDir)).root.replace(/\\$/, '');
      const ps = `(Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='${drive.replace(/'/g, "''")}'").FreeSpace`;
      const out = execFileSync(
        'powershell.exe',
        ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps],
        { encoding: 'utf8', windowsHide: true, timeout: 10000 },
      ).trim();
      const n = Number(out);
      if (Number.isFinite(n) && n >= 0) return n;
    } catch (_) {}
  }
  return null;
}

function assertDiskSpace(targetDir, requiredBytes, send) {
  const free = getFreeBytes(targetDir);
  if (free == null) {
    safeSend(send, { type: 'log', message: '[预检] 无法读取磁盘剩余空间，继续安装。' });
    return;
  }
  if (free < requiredBytes) {
    throw new Error(
      `磁盘空间不足：至少需要 ${formatBytes(requiredBytes)}，当前剩余 ${formatBytes(free)}。请清理空间或更换安装目录。`
    );
  }
  safeSend(send, {
    type: 'log',
    message: `[预检] 磁盘空间充足：剩余 ${formatBytes(free)}，预计需要 ${formatBytes(requiredBytes)}。`,
  });
}

function inspectZip(zipPath) {
  return new Promise((resolve, reject) => {
    yauzl.open(zipPath, { lazyEntries: false }, (err, zipfile) => {
      if (err) return reject(err);
      const info = { files: 0, uncompressedBytes: 0, hasEngine: false, unsafeEntries: [] };
      zipfile.on('entry', (entry) => {
        if (entry.fileName.endsWith('/')) return;
        const n = entry.fileName.replace(/\\/g, '/');
        if (n.includes('..') || path.isAbsolute(n)) {
          info.unsafeEntries.push(entry.fileName);
        }
        info.files += 1;
        info.uncompressedBytes += Number(entry.uncompressedSize || 0);
        if (n === 'autoscriptor-engine.exe' || n.endsWith('/autoscriptor-engine.exe')) {
          info.hasEngine = true;
        }
      });
      zipfile.on('end', () => resolve(info));
      zipfile.on('error', reject);
    });
  });
}

function addReportCheck(report, key, ok, detail, extra = {}) {
  const check = { key, ok, detail, ...extra };
  report.checks.push(check);
  if (ok === false) report.errors.push(detail);
  return check;
}

function finishDryRunReport(report) {
  report.ok = report.errors.length === 0;
  return report;
}

async function dryRunPackagedInstall(opts) {
  const {
    installRoot,
    resourcesPath,
    zipPath: zipPathOpt,
    exeDir,
    portableExePath,
    appVersion,
    userDataPath,
    skipRegistry,
    skipMumuConfig,
  } = opts || {};

  const report = {
    kind: 'packaged-install',
    ok: false,
    installRoot: '',
    zipPath: '',
    version: String(appVersion || '1.0.0'),
    checks: [],
    warnings: [],
    errors: [],
    plan: {
      mode: 'fresh',
      actions: [],
      sideEffects: [],
    },
  };

  try {
    const rootInput = String(installRoot || '').trim();
    if (!rootInput) {
      addReportCheck(report, 'installRoot', false, '未选择安装目录');
      return finishDryRunReport(report);
    }
    const rootResolved = path.resolve(rootInput);
    report.installRoot = rootResolved;

    const rootCheck = validatePackagedInstallRoot(rootResolved);
    report.plan.mode = rootCheck.exists && rootCheck.managed ? 'repair-or-upgrade' : 'fresh';
    report.plan.installRoot = {
      exists: rootCheck.exists,
      managed: rootCheck.managed,
      entryCount: rootCheck.entryCount,
    };
    addReportCheck(
      report,
      'installRoot',
      rootCheck.ok,
      rootCheck.ok
        ? (rootCheck.exists ? '安装目录可写；将按现有目录状态执行' : '父目录可写；安装时会创建目标目录')
        : rootCheck.reason,
      rootCheck,
    );

    const zipPath = resolveBackendZipPath({ zipPath: zipPathOpt, exeDir, resourcesPath });
    report.zipPath = zipPath;
    if (!zipPath || !fs.existsSync(zipPath)) {
      addReportCheck(report, 'backendZip', false, '找不到 backend.zip');
      return finishDryRunReport(report);
    }

    const zipInfo = await inspectZip(zipPath);
    const zipSize = fs.statSync(zipPath).size;
    report.plan.backend = {
      zipPath,
      destination: path.join(rootResolved, 'backend'),
      stagingPattern: path.join(rootResolved, '.backend.new.<timestamp>.<pid>'),
      files: zipInfo.files,
      zipBytes: zipSize,
      uncompressedBytes: zipInfo.uncompressedBytes,
      hasExistingBackend: fs.existsSync(path.join(rootResolved, 'backend')),
      transactionalSwap: true,
      rollbackOnSwapFailure: true,
    };
    addReportCheck(
      report,
      'backendZip',
      true,
      `backend.zip 可读取：${zipInfo.files} 个文件，解压后约 ${formatBytes(zipInfo.uncompressedBytes)}`,
      { files: zipInfo.files, uncompressedBytes: zipInfo.uncompressedBytes },
    );
    addReportCheck(
      report,
      'backendEngine',
      zipInfo.hasEngine,
      zipInfo.hasEngine ? 'backend.zip 包含 autoscriptor-engine.exe' : 'backend.zip 缺少 autoscriptor-engine.exe',
    );
    addReportCheck(
      report,
      'backendZipPaths',
      zipInfo.unsafeEntries.length === 0,
      zipInfo.unsafeEntries.length === 0
        ? 'backend.zip 路径安全'
        : 'backend.zip 包含非法路径: ' + zipInfo.unsafeEntries.slice(0, 5).join(', '),
      { unsafeEntries: zipInfo.unsafeEntries.slice(0, 20) },
    );

    const requiredBytes = zipInfo.uncompressedBytes + zipSize + 512 * 1024 * 1024;
    const diskTarget = rootCheck.exists ? rootResolved : path.dirname(rootResolved);
    const freeBytes = getFreeBytes(diskTarget);
    report.plan.disk = {
      target: diskTarget,
      freeBytes,
      requiredBytes,
    };
    if (freeBytes == null) {
      const msg = '无法读取磁盘剩余空间；正式安装时仍会再次检查';
      report.warnings.push(msg);
      addReportCheck(report, 'diskSpace', null, msg, { requiredBytes });
    } else {
      addReportCheck(
        report,
        'diskSpace',
        freeBytes >= requiredBytes,
        freeBytes >= requiredBytes
          ? `磁盘空间充足：剩余 ${formatBytes(freeBytes)}，预计需要 ${formatBytes(requiredBytes)}`
          : `磁盘空间不足：剩余 ${formatBytes(freeBytes)}，预计需要 ${formatBytes(requiredBytes)}`,
        { freeBytes, requiredBytes },
      );
    }

    const dataSrc = exeDir ? path.join(exeDir, 'data') : '';
    const dataDest = resolveRuntimeDataRoot(rootResolved, userDataPath);
    const dataPlan = planPackagedDataMerge(dataSrc, dataDest);
    const runtimePlan = inspectPackagedRuntimeData(dataSrc, dataDest, { previewMumu: !skipMumuConfig });
    report.plan.data = {
      source: dataSrc,
      destination: dataDest,
      ...dataPlan,
      preservePolicy: ['config.json', 'accounts/*.json', 'custom_task/**', 'battle_character/**'],
    };
    report.plan.runtime = runtimePlan;
    for (const w of runtimePlan.warnings) report.warnings.push(w);
    addReportCheck(
      report,
      'runtimeData',
      runtimePlan.errors.length === 0,
      runtimePlan.errors.length === 0
        ? `runtime data OK; config=${runtimePlan.effectiveConfigSource || 'unknown'}`
        : 'runtime data validation failed: ' + runtimePlan.errors.join('; '),
      {
        effectiveConfigPath: runtimePlan.effectiveConfigPath,
        effectiveConfigSource: runtimePlan.effectiveConfigSource,
        checks: runtimePlan.checks,
        mumuPreview: runtimePlan.mumuPreview,
      },
    );
    if (!dataPlan.sourceExists) {
      report.warnings.push('未找到随包 data 目录；正式安装会跳过基础数据合并');
    }

    const launcherDest = path.join(rootResolved, '造笔.exe');
    const launcherSource = portableExePath || '';
    const launcherSourceExists = !!launcherSource && fs.existsSync(launcherSource);
    report.plan.launcher = {
      source: launcherSource,
      destination: launcherDest,
      willCopy: process.platform === 'win32' && launcherSourceExists,
    };
    if (process.platform === 'win32' && !launcherSourceExists) {
      report.warnings.push('未找到安装包可执行文件路径；正式安装可能无法写入日常启动器 造笔.exe');
    }

    const markerPath = path.join(userDataPath || '', 'install.json');
    report.plan.marker = {
      path: markerPath,
      willWrite: !!userDataPath,
      dataRoot: dataDest,
    };
    if (!userDataPath) {
      report.warnings.push('未提供 Electron userData 路径；正式安装无法记录 install.json');
    }

    report.plan.uninstall = {
      ps1: path.join(rootResolved, 'Uninstall.ps1'),
      keepDataBat: path.join(rootResolved, '卸载造笔.bat'),
      removeAllBat: path.join(rootResolved, '彻底卸载造笔.bat'),
      registryKey: 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\AutoScriptorZao',
      willRegisterInAppsAndFeatures: !skipRegistry,
    };

    report.plan.mumuConfig = {
      willAutoDetectAndWriteConfig: !skipMumuConfig,
    };

    report.plan.actions.push(
      '读取并校验 backend.zip',
      '解压到 .backend.new.<timestamp>.<pid> 临时目录',
      report.plan.backend.hasExistingBackend ? '备份并事务切换现有 backend' : '创建新的 backend',
      '合并随包 data 到用户可写数据目录，同时保留用户配置与自定义任务',
      '写入 userData/install.json 安装标记',
      '写入卸载脚本和应用程序卸载入口',
    );
    if (!skipMumuConfig) {
      report.plan.actions.push('自动检测 MuMu/ADB 配置并写回 config.json');
    }
    report.plan.sideEffects.push('dry-run 本身不创建目录、不写注册表、不复制文件、不修改配置');
  } catch (e) {
    report.errors.push(e && e.message ? e.message : String(e));
  }

  return finishDryRunReport(report);
}

async function dryRunApplyBackendIncremental(opts) {
  const { installRoot, zipPath } = opts || {};
  const report = {
    kind: 'backend-incremental',
    ok: false,
    installRoot: '',
    zipPath: '',
    checks: [],
    warnings: [],
    errors: [],
    plan: {
      replace: 0,
      add: 0,
      remove: 0,
      skip: 0,
      actions: [],
    },
  };

  let zipfile = null;
  try {
    const rootInput = String(installRoot || '').trim();
    if (!rootInput) {
      addReportCheck(report, 'installRoot', false, '未选择安装目录');
      return finishDryRunReport(report);
    }
    const rootResolved = path.resolve(rootInput);
    report.installRoot = rootResolved;
    report.zipPath = String(zipPath || '').trim();
    const backendDest = path.join(rootResolved, 'backend');
    if (!report.zipPath || !fs.existsSync(report.zipPath)) {
      addReportCheck(report, 'incrementalZip', false, '找不到 backend_incremental.zip');
      return finishDryRunReport(report);
    }
    addReportCheck(report, 'incrementalZip', true, '增量包可读取');

    if (!fs.existsSync(backendDest) || !fs.statSync(backendDest).isDirectory()) {
      addReportCheck(report, 'backendDir', false, 'backend 目录不存在，请先完整安装');
      return finishDryRunReport(report);
    }
    addReportCheck(report, 'backendDir', true, 'backend 目录存在');

    const freeBytes = getFreeBytes(rootResolved);
    const requiredBytes = dirSizeSync(backendDest) + fs.statSync(report.zipPath).size + 512 * 1024 * 1024;
    if (freeBytes == null) {
      const msg = '无法读取磁盘剩余空间；正式增量更新时仍会再次检查';
      report.warnings.push(msg);
      addReportCheck(report, 'diskSpace', null, msg, { requiredBytes });
    } else {
      addReportCheck(
        report,
        'diskSpace',
        freeBytes >= requiredBytes,
        freeBytes >= requiredBytes
          ? `磁盘空间充足：剩余 ${formatBytes(freeBytes)}，预计需要 ${formatBytes(requiredBytes)}`
          : `磁盘空间不足：剩余 ${formatBytes(freeBytes)}，预计需要 ${formatBytes(requiredBytes)}`,
        { freeBytes, requiredBytes },
      );
    }

    let map;
    ({ zipfile, map } = await openZipWithEntryMap(report.zipPath));
    const mEntry = map.get('incremental_manifest.json');
    if (!mEntry) {
      addReportCheck(report, 'manifest', false, 'ZIP 中未找到 incremental_manifest.json');
      return finishDryRunReport(report);
    }
    const raw = await readZipEntryBuffer(zipfile, mEntry);
    const manifest = JSON.parse(raw.toString('utf8'));
    if (!manifest || manifest.format !== 'backend_incremental_v1') {
      addReportCheck(report, 'manifest', false, '不支持的增量清单格式（需要 backend_incremental_v1）');
      return finishDryRunReport(report);
    }
    addReportCheck(report, 'manifest', true, '增量清单格式正确');
    report.plan.manifest = {
      fromLabel: manifest.from_label || '',
      toLabel: manifest.to_label || '',
    };

    const removes = Array.isArray(manifest.remove) ? manifest.remove : [];
    const entries = Array.isArray(manifest.entries) ? manifest.entries : [];
    let engineWillExist = fs.existsSync(path.join(backendDest, 'autoscriptor-engine.exe'));

    for (const relRaw of removes) {
      const rel = String(relRaw).replace(/\\/g, '/');
      if (rel.includes('..')) {
        addReportCheck(report, 'removePath', false, '非法删除路径: ' + relRaw);
        continue;
      }
      if (rel === 'autoscriptor-engine.exe') engineWillExist = false;
      if (fs.existsSync(safeJoin(backendDest, rel))) report.plan.remove += 1;
    }

    for (const e of entries) {
      const rel = String(e.path).replace(/\\/g, '/');
      if (rel.includes('..') || rel === 'incremental_manifest.json') {
        addReportCheck(report, 'entryPath', false, '非法路径: ' + e.path);
        continue;
      }
      const target = safeJoin(backendDest, rel);
      const zipEnt = map.get(rel);
      if (!zipEnt) {
        addReportCheck(report, 'entryZip', false, 'ZIP 内缺少文件: ' + rel);
        continue;
      }
      const buf = await readZipEntryBuffer(zipfile, zipEnt);
      const zipSha = sha256Buffer(buf);
      if (zipSha !== e.new_sha256) {
        addReportCheck(report, 'entrySha256', false, `ZIP 文件校验不匹配: ${rel}`);
        continue;
      }

      if (e.action === 'replace') {
        if (!fs.existsSync(target)) {
          addReportCheck(report, 'entryBaseline', false, `缺少待替换文件: ${rel}`);
          continue;
        }
        const cur = sha256FileSync(target);
        if (cur === e.new_sha256) {
          report.plan.skip += 1;
        } else if (cur !== e.old_sha256) {
          addReportCheck(report, 'entryBaseline', false, `基线不匹配，无法应用增量: ${rel}`);
        } else {
          report.plan.replace += 1;
        }
      } else if (e.action === 'add') {
        if (fs.existsSync(target)) {
          const cur = sha256FileSync(target);
          if (cur === e.new_sha256) {
            report.plan.skip += 1;
          } else {
            addReportCheck(report, 'entryExists', false, `路径已存在且内容不一致: ${rel}`);
          }
        } else {
          report.plan.add += 1;
        }
      } else {
        addReportCheck(report, 'entryAction', false, '未知条目 action: ' + e.action);
      }
      if (rel === 'autoscriptor-engine.exe' && ['replace', 'add'].includes(e.action)) engineWillExist = true;
    }

    addReportCheck(
      report,
      'backendEngine',
      engineWillExist,
      engineWillExist ? '更新后仍会保留 autoscriptor-engine.exe' : '更新后会缺少 autoscriptor-engine.exe',
    );
    report.plan.actions.push(
      '复制当前 backend 到 .backend.incremental.<timestamp>.<pid>',
      '校验 manifest 中的旧文件 SHA-256',
      '写入新增/替换文件并校验新 SHA-256',
      '事务切换 backend，失败时保留旧版本',
    );
  } catch (e) {
    report.errors.push(e && e.message ? e.message : String(e));
  } finally {
    try {
      if (zipfile) zipfile.close();
    } catch (_) {}
  }

  return finishDryRunReport(report);
}

/**
 * 打开 zip，收集 entry 名 -> entry（lazyEntries:false，便于随后对同一 zipfile 多次 openReadStream）。
 */
function openZipWithEntryMap(zipPath) {
  return new Promise((resolve, reject) => {
    // autoClose 默认 true 会在 emit('end') 前关闭 zip，导致后续无法 openReadStream 解压条目
    yauzl.open(zipPath, { lazyEntries: false, autoClose: false }, (err, zipfile) => {
      if (err) return reject(err);
      const map = new Map();
      zipfile.on('entry', (entry) => {
        if (!/\/$/.test(entry.fileName)) {
          const n = entry.fileName.replace(/\\/g, '/');
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
    const dir = path.dirname(destPath);
    fs.mkdirSync(dir, { recursive: true });
    const tmp = destPath + '.tmp.' + process.pid;
    zipfile.openReadStream(entry, (err, rs) => {
      if (err) return reject(err);
      const ws = fs.createWriteStream(tmp);
      rs.on('error', reject);
      ws.on('error', reject);
      ws.on('close', () => resolve(tmp));
      rs.pipe(ws);
    });
  }).then((tmp) => {
    try {
      if (fs.existsSync(destPath)) fs.unlinkSync(destPath);
    } catch (_) {}
    fs.renameSync(tmp, destPath);
  });
}

function verifyBackendDir(backendDir) {
  const engine = path.join(backendDir, process.platform === 'win32' ? 'autoscriptor-engine.exe' : 'autoscriptor-engine');
  if (!fs.existsSync(engine) || !fs.statSync(engine).isFile()) {
    throw new Error('backend 校验失败：缺少 autoscriptor-engine.exe');
  }
}

async function removeDirWithRetry(targetDir, send, label = '目录') {
  const max = 5;
  let lastErr = null;
  for (let i = 0; i < max; i++) {
    try {
      fs.rmSync(targetDir, { recursive: true, force: true });
      return null;
    } catch (e) {
      lastErr = e;
      const msg = String(e && e.message ? e.message : e);
      safeSend(send, { type: 'log', message: `[重试 ${i + 1}/${max}] 删除${label}: ${msg}` });
      if (i < max - 1) await sleepMs(600 * (i + 1));
    }
  }
  return lastErr || new Error(`无法删除${label}: ${targetDir}`);
}

function isTransientFsLockError(err) {
  const code = String(err && err.code ? err.code : '').toUpperCase();
  return ['EBUSY', 'EPERM', 'EACCES', 'ENOTEMPTY'].includes(code);
}

function releaseInstallLocksForRoot(installRoot, send) {
  if (process.platform !== 'win32') return;
  const root = path.resolve(installRoot);
  const ps = `
$ErrorActionPreference = 'Continue'
$root = ${JSON.stringify(root)}
$skip = @(${process.pid}, $PID)
$killed = @()
try {
  Get-CimInstance Win32_Process | Where-Object {
    ($skip -notcontains [int]$_.ProcessId) -and (
      ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) -or
      ($_.CommandLine -and $_.CommandLine.IndexOf($root, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
    )
  } | ForEach-Object {
    $killed += ([string]$_.ProcessId + ':' + [string]$_.Name)
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }
} catch {
  Write-Output ('error:' + $_.Exception.Message)
}
if ($killed.Count -gt 0) { Write-Output ('killed:' + ($killed -join ',')) }
`;
  try {
    const result = spawnSync('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps], {
      encoding: 'utf8',
      timeout: 15000,
      windowsHide: true,
    });
    const out = String(result.stdout || '').trim();
    const err = String(result.stderr || '').trim();
    if (out) safeSend(send, { type: 'log', message: `[锁释放] ${out}` });
    if (err) safeSend(send, { type: 'log', message: `[锁释放] ${err}` });
  } catch (e) {
    safeSend(send, { type: 'log', message: `[锁释放] 进程检查失败: ${e && e.message ? e.message : e}` });
  }
}

async function renameWithRetry(src, dest, send, label, installRoot) {
  const max = 10;
  let lastErr = null;
  for (let i = 0; i < max; i++) {
    try {
      fs.renameSync(src, dest);
      return;
    } catch (e) {
      lastErr = e;
      const msg = e && e.message ? e.message : String(e);
      if (!isTransientFsLockError(e) || i === max - 1) throw e;
      safeSend(send, { type: 'log', message: `[重试 ${i + 1}/${max}] ${label} 被占用，尝试释放锁后重试: ${msg}` });
      releaseInstallLocksForRoot(installRoot, send);
      await sleepMs(Math.min(800 * (i + 1), 3000));
    }
  }
  throw lastErr || new Error(`${label} 重命名失败: ${src} -> ${dest}`);
}

async function swapBackendDirectory(stagingDir, backendDest, send) {
  const backupDir = `${backendDest}.bak.${stamp()}.${process.pid}`;
  const installRoot = path.dirname(backendDest);
  let oldMoved = false;
  let newMoved = false;
  try {
    if (fs.existsSync(backendDest)) {
      await renameWithRetry(backendDest, backupDir, send, '备份旧 backend', installRoot);
      oldMoved = true;
      safeSend(send, { type: 'log', message: `[事务] 已备份旧 backend: ${backupDir}` });
    }
    await renameWithRetry(stagingDir, backendDest, send, '切换新 backend', installRoot);
    newMoved = true;
    safeSend(send, { type: 'log', message: '[事务] 已切换到新 backend。' });
  } catch (e) {
    try {
      if (newMoved && fs.existsSync(backendDest)) {
        fs.rmSync(backendDest, { recursive: true, force: true });
      }
      if (oldMoved && fs.existsSync(backupDir) && !fs.existsSync(backendDest)) {
        await renameWithRetry(backupDir, backendDest, send, '回滚旧 backend', installRoot);
      }
    } catch (rollbackErr) {
      throw new Error(
        `backend 切换失败，且回滚也失败。切换错误: ${e.message}; 回滚错误: ${rollbackErr.message}`
      );
    }
    throw new Error(
      'backend 切换失败，已回滚旧版本。原始错误: '
      + (e && e.message ? e.message : String(e))
      + '。若多次重试仍失败，通常是旧引擎进程、杀毒软件或系统索引持有文件句柄；请关闭造笔/MuMu 相关进程，必要时重启电脑后重试安装或更新。'
    );
  }

  if (oldMoved && fs.existsSync(backupDir)) {
    const rmErr = await removeDirWithRetry(backupDir, send, '旧 backend 备份');
    if (rmErr) {
      safeSend(send, {
        type: 'warning',
        message: '旧 backend 备份删除失败',
        detail: `${backupDir}\n${rmErr.message || rmErr}`,
      });
    }
  }
}

function shouldOverwritePackagedData(rel) {
  const n = rel.replace(/\\/g, '/').toLowerCase();
  if (n === 'config.json') return false;
  if (n.startsWith('accounts/') && n.endsWith('.json')) return false;
  if (n.startsWith('custom_task/')) return false;
  if (n.startsWith('battle_character/')) return false;
  return true;
}

function copyPackagedDataPreservingUserFiles(dataSrc, dataDest, send) {
  if (!fs.existsSync(dataSrc)) {
    safeSend(send, { type: 'log', message: '[数据] 未找到随包 data 目录（可忽略）' });
    return;
  }
  fs.mkdirSync(dataDest, { recursive: true });
  let copied = 0;
  let kept = 0;
  const walk = (srcDir) => {
    for (const entry of fs.readdirSync(srcDir, { withFileTypes: true })) {
      const src = path.join(srcDir, entry.name);
      const rel = path.relative(dataSrc, src);
      const dest = path.join(dataDest, rel);
      if (entry.isDirectory()) {
        fs.mkdirSync(dest, { recursive: true });
        walk(src);
        continue;
      }
      if (!entry.isFile()) continue;
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      if (fs.existsSync(dest) && !shouldOverwritePackagedData(rel)) {
        kept += 1;
        continue;
      }
      fs.copyFileSync(src, dest);
      copied += 1;
    }
  };
  walk(dataSrc);
  safeSend(send, {
    type: 'log',
    message: `[数据] 已合并到 ${dataDest}（复制/更新 ${copied} 个，保留用户文件 ${kept} 个）`,
  });
}

function applyConfigDefaultsFromPackagedData(dataSrc, dataDest, send) {
  const sourceConfig = readJsonObject(path.join(dataSrc, 'config.json'));
  const sourceTemplate = readJsonObject(path.join(dataSrc, 'config template.json'));
  const defaults = chooseConfigDefaults(sourceTemplate, sourceConfig);
  const targetPath = path.join(dataDest, 'config.json');
  if (!defaults.data || !fs.existsSync(targetPath)) {
    return { ok: false, changed: false, missingKeys: [], reason: 'config defaults or target config missing' };
  }
  const current = readJsonObject(targetPath);
  if (!current.ok) {
    return { ok: false, changed: false, missingKeys: [], reason: current.error || 'target config invalid' };
  }
  const mergePlan = previewConfigDefaultMerge(defaults.data, current.data);
  if (!mergePlan.missingKeys.length) {
    return { ok: true, changed: false, missingKeys: [] };
  }
  fs.writeFileSync(targetPath, JSON.stringify(mergePlan.merged, null, 2) + '\n', 'utf8');
  safeSend(send, {
    type: 'log',
    message: `[配置] 已用随包模板补齐 ${mergePlan.missingKeys.length} 个缺失配置项（保留原有用户值）`,
  });
  return { ok: true, changed: true, missingKeys: mergePlan.missingKeys };
}

/**
 * 将增量包应用到 installRoot/backend/：先删 manifest.remove，再按条目校验并解压覆盖。
 * @param {{ installRoot: string, zipPath: string, send: (data: object) => void }} opts
 */
async function applyBackendIncremental(opts) {
  const { installRoot, zipPath, send } = opts;
  if (!zipPath || !fs.existsSync(zipPath)) {
    throw new Error('找不到增量包文件: ' + (zipPath || ''));
  }
  const rootResolved = path.resolve(installRoot);
  const backendDest = path.join(rootResolved, 'backend');
  if (!fs.existsSync(backendDest) || !fs.statSync(backendDest).isDirectory()) {
    throw new Error('backend 目录不存在，请先完成完整安装（解压 backend.zip）');
  }

  assertDiskSpace(rootResolved, dirSizeSync(backendDest) + fs.statSync(zipPath).size + 512 * 1024 * 1024, send);
  const stagingDir = path.join(rootResolved, `.backend.incremental.${stamp()}.${process.pid}`);
  let zipfile = null;
  let map = null;
  try {
    safeSend(send, { type: 'progress', percent: 2, message: '准备事务更新…' });
    safeSend(send, { type: 'log', message: `[事务] 复制当前 backend 到临时目录: ${stagingDir}` });
    fs.cpSync(backendDest, stagingDir, { recursive: true });
    ({ zipfile, map } = await openZipWithEntryMap(zipPath));
    const mEntry = map.get('incremental_manifest.json');
    if (!mEntry) {
      throw new Error('ZIP 中未找到 incremental_manifest.json');
    }
    const raw = await readZipEntryBuffer(zipfile, mEntry);
    const manifest = JSON.parse(raw.toString('utf8'));
    if (!manifest || manifest.format !== 'backend_incremental_v1') {
      throw new Error('不支持的增量清单格式（需要 backend_incremental_v1）');
    }

    const entries = Array.isArray(manifest.entries) ? manifest.entries : [];
    const removes = Array.isArray(manifest.remove) ? manifest.remove : [];
    const totalSteps = removes.length + entries.length;
    let step = 0;

    const bump = (msg) => {
      step += 1;
      const pct = totalSteps <= 0 ? 100 : Math.min(99, 5 + Math.floor((90 * step) / totalSteps));
      safeSend(send, { type: 'progress', percent: pct, message: msg || `增量 ${step}/${totalSteps}` });
    };

    if (manifest.from_label || manifest.to_label) {
      safeSend(send, {
        type: 'log',
        message: `[增量] 清单: ${manifest.from_label || '?'} → ${manifest.to_label || '?'}`,
      });
    }

    for (const rel of removes) {
      const n = String(rel).replace(/\\/g, '/');
      if (n.includes('..')) throw new Error('非法删除路径: ' + rel);
      const p = safeJoin(stagingDir, n);
      if (fs.existsSync(p)) {
        fs.rmSync(p, { force: true, recursive: true });
        safeSend(send, { type: 'log', message: `[增量] 已删除 ${n}` });
      }
      bump(`已处理删除 ${step}/${totalSteps}`);
    }

    let ei = 0;
    for (const e of entries) {
      ei += 1;
      const rel = String(e.path).replace(/\\/g, '/');
      if (rel.includes('..') || rel === 'incremental_manifest.json') {
        throw new Error('非法路径: ' + e.path);
      }
      const target = safeJoin(stagingDir, rel);
      const zipEnt = map.get(rel);
      if (!zipEnt) {
        throw new Error(`ZIP 内缺少文件: ${rel}`);
      }

      if (e.action === 'replace') {
        if (!fs.existsSync(target)) {
          throw new Error(
            `缺少待替换文件「${rel}」，与增量基线不一致。请使用完整 backend.zip 重装，或换用与当前引擎匹配的增量包。`
          );
        }
        const cur = sha256FileSync(target);
        if (cur === e.new_sha256) {
          safeSend(send, { type: 'log', message: `[增量] 已跳过(已是新版) ${rel}` });
          bump(`跳过 ${ei}/${entries.length}`);
          continue;
        }
        if (cur !== e.old_sha256) {
          throw new Error(
            `基线不匹配，无法应用增量: ${rel}。当前引擎与发布此增量包时的「旧版」不一致，请下载完整安装包或匹配版本的增量包。`
          );
        }
      } else if (e.action === 'add') {
        if (fs.existsSync(target)) {
          const cur = sha256FileSync(target);
          if (cur === e.new_sha256) {
            safeSend(send, { type: 'log', message: `[增量] 已存在且一致 ${rel}` });
            bump(`跳过 ${ei}/${entries.length}`);
            continue;
          }
          throw new Error(`路径已存在且内容不一致: ${rel}，请先完整重装再试增量。`);
        }
      } else {
        throw new Error('未知条目 action: ' + e.action);
      }

      await extractZipEntryToPath(zipfile, zipEnt, target);
      const got = sha256FileSync(target);
      if (got !== e.new_sha256) {
        throw new Error(`校验失败 ${rel}: 期望 SHA256 ${e.new_sha256}，得到 ${got}`);
      }
      safeSend(send, { type: 'log', message: `[增量] 已更新 ${rel}` });
      bump(`写入 ${ei}/${entries.length}`);
    }

    verifyBackendDir(stagingDir);
    await swapBackendDirectory(stagingDir, backendDest, send);
    safeSend(send, { type: 'progress', percent: 100, message: '增量更新完成' });
    safeSend(send, { type: 'log', message: '[增量] 引擎增量已应用，可重启造笔。' });
    safeSend(send, { type: 'complete' });
  } finally {
    try {
      if (zipfile) zipfile.close();
    } catch (_) {}
    if (fs.existsSync(stagingDir)) {
      await removeDirWithRetry(stagingDir, send, '增量临时目录');
    }
  }
}

/**
 * 将发行版 portable 安装包本体复制为安装目录下的「造笔.exe」，供用户日常启动（与 AutoScriptor_Zao_Install.exe 安装向导区分）。
 */
function copyDailyLauncher(installRoot, portableExePath, send) {
  if (process.platform !== 'win32') return;
  const root = path.resolve(installRoot);
  const dest = path.join(root, '造笔.exe');
  if (!portableExePath || !fs.existsSync(portableExePath)) {
    safeSend(send, {
      type: 'log',
      message: '[启动器] 未找到安装包可执行文件路径，跳过写入 造笔.exe',
    });
    return;
  }
  try {
    fs.copyFileSync(portableExePath, dest);
    safeSend(send, { type: 'log', message: `[启动器] 已写入日常启动器: ${dest}` });
  } catch (e) {
    const msg = e && e.message ? e.message : String(e);
    safeSend(send, { type: 'log', message: `[启动器] 写入 造笔.exe 失败: ${msg}` });
    throw new Error('无法写入安装目录下的 造笔.exe：' + msg);
  }
}

function registerUninstall(installRoot, displayVersion, opts = {}) {
  const ps1 = path.join(installRoot, 'Uninstall.ps1');
  const { execFileSync } = require('child_process');
  const sysRoot = process.env.SystemRoot || 'C:\\Windows';
  const psExe = path.join(sysRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  // 「应用和功能」调 UninstallString：直接填 .bat 在部分系统上无效；用 PowerShell -File 执行卸载脚本最稳
  const uninstallString = `"${psExe}" -NoProfile -ExecutionPolicy Bypass -File "${ps1}"`;
  if (opts && opts.skipRegistry) {
    safeSend(opts.send, { type: 'log', message: '[卸载] 测试模式：跳过写入 Windows 应用卸载注册表' });
    return { ok: true, skipped: true, uninstallString };
  }
  const ver = String(displayVersion || '1.0.0');
  const iconExe = path.join(installRoot, '造笔.exe');
  const ps = `
$ErrorActionPreference = 'Stop'
$key = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\AutoScriptorZao'
New-Item -Path $key -Force | Out-Null
Set-ItemProperty -LiteralPath $key -Name DisplayName -Value '造笔' -Type String
Set-ItemProperty -LiteralPath $key -Name DisplayVersion -Value ${JSON.stringify(ver)} -Type String
Set-ItemProperty -LiteralPath $key -Name InstallLocation -Value ${JSON.stringify(installRoot)} -Type String
Set-ItemProperty -LiteralPath $key -Name UninstallString -Value ${JSON.stringify(uninstallString)} -Type String
Set-ItemProperty -LiteralPath $key -Name QuietUninstallString -Value ${JSON.stringify(uninstallString)} -Type String
Set-ItemProperty -LiteralPath $key -Name Publisher -Value 'AutoScriptor' -Type String
if (Test-Path -LiteralPath ${JSON.stringify(iconExe)}) {
  Set-ItemProperty -LiteralPath $key -Name DisplayIcon -Value ${JSON.stringify(iconExe)} -Type String
}
`;
  try {
    execFileSync('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps], {
      windowsHide: true,
      encoding: 'utf8',
    });
    return { ok: true, skipped: false, uninstallString };
  } catch (e) {
    console.warn('[install-packaged] 注册卸载失败（可忽略）:', e && e.message ? e.message : e);
    return { ok: false, skipped: false, uninstallString, error: e && e.message ? e.message : String(e) };
  }
}

async function runPackagedInstall(opts) {
  const {
    installRoot,
    resourcesPath,
    zipPath: zipPathOpt,
    exeDir,
    portableExePath,
    appVersion,
    userDataPath,
    send,
    skipMumuConfig = false,
    skipRegistry = false,
  } = opts || {};

  let zipPath = resolveBackendZipPath({ zipPath: zipPathOpt, exeDir, resourcesPath });
  if (!fs.existsSync(zipPath)) {
    throw new Error(
      '找不到 backend.zip（应在 exe 同级或 resources 下）。请用完整脚本生成 dist/backend.zip 后重新打包 Electron。'
    );
  }

  const rootResolved = path.resolve(String(installRoot || '').trim());
  const rootCheck = validatePackagedInstallRoot(rootResolved);
  if (!rootCheck.ok) throw new Error(rootCheck.reason);

  const zipInfo = await inspectZip(zipPath);
  if (!zipInfo.hasEngine) {
    throw new Error('backend.zip 校验失败：压缩包内缺少 autoscriptor-engine.exe');
  }
  if (zipInfo.unsafeEntries.length) {
    throw new Error('backend.zip 校验失败：包含非法路径: ' + zipInfo.unsafeEntries.slice(0, 5).join(', '));
  }
  assertDiskSpace(
    rootResolved,
    zipInfo.uncompressedBytes + fs.statSync(zipPath).size + 512 * 1024 * 1024,
    send,
  );
  const dataSrc = path.join(exeDir, 'data');
  const dataDest = resolveRuntimeDataRoot(rootResolved, userDataPath);
  const runtimePlan = inspectPackagedRuntimeData(dataSrc, dataDest, { previewMumu: false });
  if (runtimePlan.errors.length) {
    throw new Error('runtime data validation failed: ' + runtimePlan.errors.join('; '));
  }
  fs.mkdirSync(rootResolved, { recursive: true });

  const backendDest = path.join(rootResolved, 'backend');
  const stagingDir = path.join(rootResolved, `.backend.new.${stamp()}.${process.pid}`);
  if (fs.existsSync(stagingDir)) {
    const errRm = await removeDirWithRetry(stagingDir, send, '历史解压临时目录');
    if (errRm) throw errRm;
  }
  fs.mkdirSync(stagingDir, { recursive: true });

  safeSend(send, { type: 'log', message: `[解压] 压缩包: ${zipPath}` });
  safeSend(send, { type: 'log', message: `[解压] 临时目录: ${stagingDir}` });

  const total = zipInfo.files;
  safeSend(send, { type: 'log', message: `[解压] 共 ${total} 个文件，开始解压（请稍候，杀软可能拖慢速度）…` });
  safeSend(send, { type: 'progress', percent: 3, message: `准备解压（${total} 个文件）…` });

  try {
    const nativeExtract = await extractZipWithNativeTar(zipPath, stagingDir, { send, total });
    let needsJsExtract = !nativeExtract.ok;
    let stagingReset = false;
    if (nativeExtract.ok) {
      try {
        verifyBackendDir(stagingDir);
      } catch (e) {
        const msg = e && e.message ? e.message : String(e);
        safeSend(send, { type: 'log', message: `[解压] tar.exe 解压结果校验失败，回退 JS 解压：${msg}` });
        const errRm = await removeDirWithRetry(stagingDir, send, 'tar.exe 解压残留目录');
        if (errRm) throw errRm;
        fs.mkdirSync(stagingDir, { recursive: true });
        stagingReset = true;
        needsJsExtract = true;
      }
    }
    if (needsJsExtract) {
      if (nativeExtract.attempted && !stagingReset) {
        const errRm = await removeDirWithRetry(stagingDir, send, 'tar.exe 解压残留目录');
        if (errRm) throw errRm;
        fs.mkdirSync(stagingDir, { recursive: true });
      }
      const reportExtractProgress = createExtractProgressReporter({ send, total });
      await extractZip(zipPath, stagingDir, {
        onFile: (done, name) => {
          reportExtractProgress(done, name);
        },
      });
    }
    verifyBackendDir(stagingDir);
    safeSend(send, { type: 'progress', percent: 90, message: '切换引擎文件…' });
    await swapBackendDirectory(stagingDir, backendDest, send);
  } catch (e) {
    if (fs.existsSync(stagingDir)) {
      await removeDirWithRetry(stagingDir, send, '解压临时目录');
    }
    throw e;
  }

  safeSend(send, { type: 'log', message: '[解压] 引擎文件已完成' });
  safeSend(send, { type: 'progress', percent: 94, message: '合并数据文件…' });

  copyPackagedDataPreservingUserFiles(dataSrc, dataDest, send);
  applyConfigDefaultsFromPackagedData(dataSrc, dataDest, send);

  const tpl = path.join(rootResolved, 'config template.json');
  const cfg = path.join(rootResolved, 'config.json');
  if (!fs.existsSync(cfg) && fs.existsSync(tpl)) {
    fs.copyFileSync(tpl, cfg);
  }

  if (skipMumuConfig) {
    safeSend(send, { type: 'log', message: '[MuMu] 测试模式：跳过自动检测与配置写入' });
  } else {
    const { applyMumuConfig } = require('./mumu-detect.cjs');
    applyMumuConfig(rootResolved, send, { dataRoot: dataDest });
  }

  const markerPath = path.join(userDataPath, 'install.json');
  fs.mkdirSync(userDataPath, { recursive: true });
  const manifest = {
    installRoot: rootResolved,
    dataRoot: dataDest,
    version: String(appVersion || '1.0.0'),
  };
  fs.writeFileSync(markerPath, JSON.stringify(manifest, null, 2), 'utf-8');
  safeSend(send, { type: 'log', message: `[安装] 已记录安装路径: ${markerPath}` });

  safeSend(send, { type: 'progress', percent: 95, message: '写入日常启动器（造笔.exe）…' });
  copyDailyLauncher(rootResolved, portableExePath, send);

  safeSend(send, { type: 'progress', percent: 97, message: '写入卸载程序…' });
  writeUninstallPs1(rootResolved, markerPath, dataDest);
  registerUninstall(rootResolved, manifest.version, { skipRegistry, send });
  const registryNote = skipRegistry ? '；测试模式未写入「应用和功能」注册表' : '，并已注册「应用和功能」';
  safeSend(send, {
    type: 'log',
    message: `[卸载] 已写入 ${path.join(rootResolved, '卸载造笔.bat')}（保留 dataRoot）与 ${path.join(rootResolved, '彻底卸载造笔.bat')}${registryNote}`,
  });

  safeSend(send, { type: 'progress', percent: 100, message: '安装完成' });
  safeSend(send, { type: 'complete' });
}

module.exports = {
  runPackagedInstall,
  applyBackendIncremental,
  dryRunPackagedInstall,
  dryRunApplyBackendIncremental,
  writeUninstallPs1,
  __test: {
    safeJoin,
    inspectZip,
    sha256Buffer,
    sha256FileSync,
    looksLikeManagedInstallRoot,
    validatePackagedInstallRoot,
    planPackagedDataMerge,
    inspectPackagedRuntimeData,
    previewConfigDefaultMerge,
    applyConfigDefaultsFromPackagedData,
    resolveBackendZipPath,
    registerUninstall,
    shouldOverwritePackagedData,
  },
};
