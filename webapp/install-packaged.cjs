'use strict';

/**
 * 发行版（薄包）：将 resources/backend.zip 解压到用户选择的安装目录，复制 data，写 install.json，注册卸载。
 *
 * 增量包（backend_incremental.zip）：由 scripts/release/release_backend_incremental.py 对比旧版 gui.dist / backend.zip
 * 与新版生成；applyBackendIncremental 在已有 backend/ 上校验 SHA-256 后覆盖，无需全量删除解压。
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const yauzl = require('yauzl');
const { spawn } = require('child_process');

function safeJoin(dest, name) {
  const n = name.replace(/\\/g, '/');
  if (n.includes('..') || path.isAbsolute(n)) {
    throw new Error('非法 zip 路径: ' + name);
  }
  return path.join(dest, ...n.split('/'));
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

function writeUninstallPs1(installRoot, userDataInstallJson) {
  const rootResolved = path.resolve(installRoot);
  const rootJson = JSON.stringify(rootResolved);
  const markerJson = JSON.stringify(userDataInstallJson);

  const buildInner = (removeUserData) => [
    '$ErrorActionPreference = "Continue"',
    `$log = Join-Path $env:TEMP "ZaoBiUninstall-error.log"`,
    `$root = ${rootJson}`,
    `$removeUserData = ${removeUserData ? '$true' : '$false'}`,
    'function Stop-UnderRoot {',
    '  try {',
    '    Get-CimInstance Win32_Process | Where-Object {',
    '      ($_.ExecutablePath -and ($_.ExecutablePath.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase))) -or',
    '      ($_.CommandLine -and ($_.CommandLine.IndexOf($root, [System.StringComparison]::OrdinalIgnoreCase) -ge 0))',
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
    '  if (-not (Test-Path -LiteralPath $root)) { exit 0 }',
    '  Stop-UnderRoot',
    '  Start-Sleep -Milliseconds (400 + $round * 150)',
    '  if ($removeUserData) {',
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
    '    ($_.ExecutablePath -and ($_.ExecutablePath.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase))) -or',
    '    ($_.CommandLine -and ($_.CommandLine.IndexOf($root, [System.StringComparison]::OrdinalIgnoreCase) -ge 0))',
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

function safeSend(send, data) {
  if (typeof send === 'function') send(data);
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
      const info = { files: 0, uncompressedBytes: 0, hasEngine: false };
      zipfile.on('entry', (entry) => {
        if (entry.fileName.endsWith('/')) return;
        const n = entry.fileName.replace(/\\/g, '/');
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

async function swapBackendDirectory(stagingDir, backendDest, send) {
  const backupDir = `${backendDest}.bak.${stamp()}.${process.pid}`;
  let oldMoved = false;
  let newMoved = false;
  try {
    if (fs.existsSync(backendDest)) {
      fs.renameSync(backendDest, backupDir);
      oldMoved = true;
      safeSend(send, { type: 'log', message: `[事务] 已备份旧 backend: ${backupDir}` });
    }
    fs.renameSync(stagingDir, backendDest);
    newMoved = true;
    safeSend(send, { type: 'log', message: '[事务] 已切换到新 backend。' });
  } catch (e) {
    try {
      if (newMoved && fs.existsSync(backendDest)) {
        fs.rmSync(backendDest, { recursive: true, force: true });
      }
      if (oldMoved && fs.existsSync(backupDir) && !fs.existsSync(backendDest)) {
        fs.renameSync(backupDir, backendDest);
      }
    } catch (rollbackErr) {
      throw new Error(
        `backend 切换失败，且回滚也失败。切换错误: ${e.message}; 回滚错误: ${rollbackErr.message}`
      );
    }
    throw new Error('backend 切换失败，已回滚旧版本。原始错误: ' + (e && e.message ? e.message : String(e)));
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
      send({ type: 'progress', percent: pct, message: msg || `增量 ${step}/${totalSteps}` });
    };

    if (manifest.from_label || manifest.to_label) {
      send({
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
        send({ type: 'log', message: `[增量] 已删除 ${n}` });
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
          send({ type: 'log', message: `[增量] 已跳过(已是新版) ${rel}` });
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
            send({ type: 'log', message: `[增量] 已存在且一致 ${rel}` });
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
      send({ type: 'log', message: `[增量] 已更新 ${rel}` });
      bump(`写入 ${ei}/${entries.length}`);
    }

    verifyBackendDir(stagingDir);
    await swapBackendDirectory(stagingDir, backendDest, send);
    send({ type: 'progress', percent: 100, message: '增量更新完成' });
    send({ type: 'log', message: '[增量] 引擎增量已应用，可重启造笔。' });
    send({ type: 'complete' });
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
    send({
      type: 'log',
      message: '[启动器] 未找到安装包可执行文件路径，跳过写入 造笔.exe',
    });
    return;
  }
  try {
    fs.copyFileSync(portableExePath, dest);
    send({ type: 'log', message: `[启动器] 已写入日常启动器: ${dest}` });
  } catch (e) {
    const msg = e && e.message ? e.message : String(e);
    send({ type: 'log', message: `[启动器] 写入 造笔.exe 失败: ${msg}` });
    throw new Error('无法写入安装目录下的 造笔.exe：' + msg);
  }
}

function registerUninstall(installRoot, displayVersion) {
  const ps1 = path.join(installRoot, 'Uninstall.ps1');
  const { execFileSync } = require('child_process');
  const sysRoot = process.env.SystemRoot || 'C:\\Windows';
  const psExe = path.join(sysRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  // 「应用和功能」调 UninstallString：直接填 .bat 在部分系统上无效；用 PowerShell -File 执行卸载脚本最稳
  const uninstallString = `"${psExe}" -NoProfile -ExecutionPolicy Bypass -File "${ps1}"`;
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
  } catch (e) {
    console.warn('[install-packaged] 注册卸载失败（可忽略）:', e && e.message ? e.message : e);
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
  } = opts;

  let zipPath = zipPathOpt;
  if (!zipPath || !fs.existsSync(zipPath)) {
    const besideExe = path.join(exeDir, 'backend.zip');
    const inRes = path.join(resourcesPath, 'backend.zip');
    if (fs.existsSync(besideExe)) zipPath = besideExe;
    else if (fs.existsSync(inRes)) zipPath = inRes;
    else zipPath = zipPathOpt || besideExe;
  }
  if (!fs.existsSync(zipPath)) {
    throw new Error(
      '找不到 backend.zip（应在 exe 同级或 resources 下）。请用完整脚本生成 dist/backend.zip 后重新打包 Electron。'
    );
  }

  const rootResolved = path.resolve(installRoot);
  fs.mkdirSync(rootResolved, { recursive: true });

  const zipInfo = await inspectZip(zipPath);
  if (!zipInfo.hasEngine) {
    throw new Error('backend.zip 校验失败：压缩包内缺少 autoscriptor-engine.exe');
  }
  assertDiskSpace(
    rootResolved,
    zipInfo.uncompressedBytes + fs.statSync(zipPath).size + 512 * 1024 * 1024,
    send,
  );

  const backendDest = path.join(rootResolved, 'backend');
  const stagingDir = path.join(rootResolved, `.backend.new.${stamp()}.${process.pid}`);
  if (fs.existsSync(stagingDir)) {
    const errRm = await removeDirWithRetry(stagingDir, send, '历史解压临时目录');
    if (errRm) throw errRm;
  }
  fs.mkdirSync(stagingDir, { recursive: true });

  send({ type: 'log', message: `[解压] 压缩包: ${zipPath}` });
  send({ type: 'log', message: `[解压] 临时目录: ${stagingDir}` });

  const total = zipInfo.files;
  send({ type: 'log', message: `[解压] 共 ${total} 个文件，开始解压（请稍候，杀软可能拖慢速度）…` });
  send({ type: 'progress', percent: 3, message: `准备解压（${total} 个文件）…` });

  try {
    await extractZip(zipPath, stagingDir, {
      onFile: (done, name) => {
        send({ type: 'log', message: `[解压] ${done}/${total} ${name}` });
        const pct = 5 + Math.floor((84 * done) / Math.max(total, 1));
        send({ type: 'progress', percent: Math.min(pct, 89), message: `解压 ${done}/${total}` });
      },
    });
    verifyBackendDir(stagingDir);
    send({ type: 'progress', percent: 90, message: '切换引擎文件…' });
    await swapBackendDirectory(stagingDir, backendDest, send);
  } catch (e) {
    if (fs.existsSync(stagingDir)) {
      await removeDirWithRetry(stagingDir, send, '解压临时目录');
    }
    throw e;
  }

  send({ type: 'log', message: '[解压] 引擎文件已完成' });
  send({ type: 'progress', percent: 94, message: '合并数据文件…' });

  const dataSrc = path.join(exeDir, 'data');
  const dataDest = path.join(rootResolved, 'data');
  copyPackagedDataPreservingUserFiles(dataSrc, dataDest, send);

  const tpl = path.join(rootResolved, 'config template.json');
  const cfg = path.join(rootResolved, 'config.json');
  if (!fs.existsSync(cfg) && fs.existsSync(tpl)) {
    fs.copyFileSync(tpl, cfg);
  }

  const { applyMumuConfig } = require('./mumu-detect.cjs');
  applyMumuConfig(rootResolved, send);

  const markerPath = path.join(userDataPath, 'install.json');
  fs.mkdirSync(userDataPath, { recursive: true });
  const manifest = {
    installRoot: rootResolved,
    dataRoot: dataDest,
    version: String(appVersion || '1.0.0'),
  };
  fs.writeFileSync(markerPath, JSON.stringify(manifest, null, 2), 'utf-8');
  send({ type: 'log', message: `[安装] 已记录安装路径: ${markerPath}` });

  send({ type: 'progress', percent: 95, message: '写入日常启动器（造笔.exe）…' });
  copyDailyLauncher(rootResolved, portableExePath, send);

  send({ type: 'progress', percent: 97, message: '写入卸载程序…' });
  writeUninstallPs1(rootResolved, markerPath);
  registerUninstall(rootResolved, manifest.version);
  send({
    type: 'log',
    message: `[卸载] 已写入 ${path.join(rootResolved, '卸载造笔.bat')}（保留 data）与 ${path.join(rootResolved, '彻底卸载造笔.bat')}，并已注册「应用和功能」`,
  });

  send({ type: 'progress', percent: 100, message: '安装完成' });
  send({ type: 'complete' });
}

module.exports = { runPackagedInstall, applyBackendIncremental, writeUninstallPs1 };
