'use strict';

/**
 * 发行版（薄包）：将 resources/backend.zip 解压到用户选择的安装目录，复制 data，写 install.json，注册卸载。
 */
const fs = require('fs');
const path = require('path');
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
  const ps1 = path.join(installRoot, 'Uninstall.ps1');
  const body = `# 造笔 卸载脚本（关闭造笔后运行）
$ErrorActionPreference = 'SilentlyContinue'
$root = ${JSON.stringify(path.resolve(installRoot))}
$marker = ${JSON.stringify(userDataInstallJson)}
if (Test-Path $marker) { Remove-Item -LiteralPath $marker -Force }
if (Test-Path $root) { Remove-Item -LiteralPath $root -Recurse -Force }
reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\AutoScriptorZao" /f 2>$null
Write-Host "卸载完成"
pause
`;
  fs.writeFileSync(ps1, '\ufeff' + body, 'utf8');

  const bat = path.join(installRoot, '卸载造笔.bat');
  const batBody = `@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "${ps1.replace(/"/g, '\\"')}"
`;
  fs.writeFileSync(bat, batBody, 'utf8');
}

function sleepMs(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * Windows 上旧 backend 可能被 python/gui 或杀软占用，单次 rm 易 EPERM；短暂重试并给出可操作提示。
 */
async function removeBackendDirWithRetry(backendDest, send) {
  const max = 5;
  let lastErr = null;
  for (let i = 0; i < max; i++) {
    try {
      fs.rmSync(backendDest, { recursive: true, force: true });
      return null;
    } catch (e) {
      lastErr = e;
      const code = e && (e.code || e.errno);
      const msg = String(e && e.message ? e.message : e);
      if (send && i === 0) {
        send({
          type: 'log',
          message:
            '[提示] 正在删除旧 backend 目录，若被占用将重试几次。请关闭占用该目录的程序（如造笔/引擎、python.exe）后重试。',
        });
      } else if (send) {
        send({ type: 'log', message: `[重试 ${i + 1}/${max}] 删除 backend: ${msg}` });
      }
      if (i < max - 1) await sleepMs(600 * (i + 1));
    }
  }
  const hint =
    '无法删除旧目录「backend」（权限被拒绝）。请：1）在任务管理器中结束「造笔」、python、相关进程；2）暂时关闭杀毒软件或把该目录加入排除；3）换一个安装目录（建议选「文档」下的 AutoScriptor 文件夹，勿选 dist_electron 等开发输出目录）。原始错误: ';
  return new Error(hint + (lastErr && lastErr.message ? lastErr.message : String(lastErr)));
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

  const backendDest = path.join(rootResolved, 'backend');
  if (fs.existsSync(backendDest)) {
    const errRm = await removeBackendDirWithRetry(backendDest, send);
    if (errRm) throw errRm;
  }
  fs.mkdirSync(backendDest, { recursive: true });

  send({ type: 'log', message: `[解压] 压缩包: ${zipPath}` });
  send({ type: 'log', message: `[解压] 目标目录: ${backendDest}` });

  const total = await countZipFiles(zipPath);
  send({ type: 'log', message: `[解压] 共 ${total} 个文件，开始解压（请稍候，杀软可能拖慢速度）…` });
  send({ type: 'progress', percent: 3, message: `准备解压（${total} 个文件）…` });

  await extractZip(zipPath, backendDest, {
    onFile: (done, name) => {
      send({ type: 'log', message: `[解压] ${done}/${total} ${name}` });
      const pct = 5 + Math.floor((88 * done) / Math.max(total, 1));
      send({ type: 'progress', percent: Math.min(pct, 93), message: `解压 ${done}/${total}` });
    },
  });

  send({ type: 'log', message: '[解压] 引擎文件已完成' });
  send({ type: 'progress', percent: 94, message: '复制用户数据…' });

  const dataSrc = path.join(exeDir, 'data');
  const dataDest = path.join(rootResolved, 'data');
  if (fs.existsSync(dataSrc)) {
    if (fs.existsSync(dataDest)) fs.rmSync(dataDest, { recursive: true, force: true });
    fs.cpSync(dataSrc, dataDest, { recursive: true });
    send({ type: 'log', message: `[数据] 已复制到 ${dataDest}` });
  } else {
    send({ type: 'log', message: '[数据] 未找到随包 data 目录（可忽略）' });
  }

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
    version: String(appVersion || '1.0.0'),
  };
  fs.writeFileSync(markerPath, JSON.stringify(manifest, null, 2), 'utf-8');
  send({ type: 'log', message: `[安装] 已记录安装路径: ${markerPath}` });

  send({ type: 'progress', percent: 95, message: '写入日常启动器（造笔.exe）…' });
  copyDailyLauncher(rootResolved, portableExePath, send);

  send({ type: 'progress', percent: 97, message: '写入卸载程序…' });
  writeUninstallPs1(rootResolved, markerPath);
  registerUninstall(rootResolved, manifest.version);
  send({ type: 'log', message: `[卸载] 已写入 ${path.join(rootResolved, '卸载造笔.bat')}，并已注册「应用和功能」` });

  send({ type: 'progress', percent: 100, message: '安装完成' });
  send({ type: 'complete' });
}

module.exports = { runPackagedInstall };
