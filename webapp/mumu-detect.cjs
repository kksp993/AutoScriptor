'use strict';

/**
 * 与 services/installer/installer.py 中 MuMu 探测逻辑对齐（无 Python 时用于发行包）。
 * 检测优先级：Windows 注册表 → 全盘符文件系统扫描。
 */
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const COMMON_NAMES = [
  'Netease\\MuMu',
  'Netease\\MuMu Player 12',
  'MuMu',
  'MuMu Player 12',
  'Netease\\MuMu Player',
  'Netease\\MuMuPlayer',
];

/**
 * 从 Windows 注册表 Uninstall 项读取 MuMu 安装路径。
 * 使用 reg query 命令行而非 N-API，兼容 Electron 打包环境。
 */
function readRegistryMumuPaths() {
  const results = [];
  if (process.platform !== 'win32') return results;
  const roots = [
    'HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall',
    'HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall',
  ];
  const keywords = ['mumu', 'mumu player', '网易 mumu'];
  for (const root of roots) {
    let subkeys;
    try {
      subkeys = execSync(`reg query "${root}"`, { encoding: 'utf-8', timeout: 10000, stdio: ['pipe', 'pipe', 'pipe'] });
    } catch (_) { continue; }
    const lines = (subkeys || '').split(/\r?\n/).filter(l => l.trim().startsWith('HKLM'));
    for (const sub of lines) {
      try {
        const detail = execSync(`reg query "${sub.trim()}" /v DisplayName`, { encoding: 'utf-8', timeout: 5000, stdio: ['pipe', 'pipe', 'pipe'] });
        const lower = (detail || '').toLowerCase();
        if (!keywords.some(kw => lower.includes(kw))) continue;
        let loc = '';
        try {
          const locOut = execSync(`reg query "${sub.trim()}" /v InstallLocation`, { encoding: 'utf-8', timeout: 5000, stdio: ['pipe', 'pipe', 'pipe'] });
          const m = (locOut || '').match(/InstallLocation\s+REG_SZ\s+(.+)/i);
          if (m) loc = m[1].trim();
        } catch (_) { /* no InstallLocation */ }
        if (loc && fs.existsSync(loc)) {
          try {
            if (fs.statSync(loc).isDirectory()) results.push(loc);
          } catch (_) {}
        }
      } catch (_) { /* 单个子项读取失败不影响整体 */ }
    }
  }
  return results;
}

const SKIP_ROOT_DIRS = new Set([
  '$recycle.bin', 'system volume information', 'windows', 'recovery',
  'perflogs', '$winreagent', '$sysreset', 'config.msi',
  'documents and settings', 'msocache',
]);

function programFilesBases() {
  const bases = [];
  const pf = process.env.ProgramFiles || 'C:\\Program Files';
  const pf86 = process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)';
  bases.push(path.resolve(pf), path.resolve(pf86));
  for (let c = 65; c <= 90; c++) {
    const root = `${String.fromCharCode(c)}:\\`;
    try {
      if (!fs.existsSync(root)) continue;
    } catch (_) { continue; }
    bases.push(root);
    bases.push(path.join(root, 'Program Files'));
    bases.push(path.join(root, 'Program Files (x86)'));
    // 枚举盘符下的一级子目录，覆盖 X:\任意目录\Netease\MuMu 这类非标路径
    try {
      for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
        if (!entry.isDirectory()) continue;
        if (SKIP_ROOT_DIRS.has(entry.name.toLowerCase())) continue;
        bases.push(path.join(root, entry.name));
      }
    } catch (_) {}
  }
  return [...new Set(bases)];
}

/**
 * 综合注册表 + 文件系统扫描来查找 MuMu 安装目录。
 * 注册表结果优先（最准确），然后是全盘符扫描。
 */
function searchMumuFolders() {
  const seen = new Set();
  const out = [];
  const addIfNew = (p) => {
    try {
      const k = path.normalize(p).toLowerCase();
      if (!seen.has(k) && fs.existsSync(p)) {
        seen.add(k);
        out.push(p);
      }
    } catch (_) {}
  };

  for (const rp of readRegistryMumuPaths()) addIfNew(rp);

  for (const base of programFilesBases()) {
    for (const name of COMMON_NAMES) {
      addIfNew(path.join(base, name));
    }
  }
  return out;
}

function deriveFromFolder(folder) {
  const nx = path.join(folder, 'nx_main');
  const shell = path.join(folder, 'shell');
  let emu = '';
  let adb = '';
  if (fs.existsSync(nx)) {
    const ep = path.join(nx, 'MuMuManager.exe');
    const ap = path.join(nx, 'adb.exe');
    if (fs.existsSync(ep) && fs.statSync(ep).isFile()) emu = ep;
    if (fs.existsSync(ap) && fs.statSync(ap).isFile()) adb = ap;
  }
  if ((!emu || !adb) && fs.existsSync(shell)) {
    const ep = path.join(shell, 'MuMuPlayer.exe');
    const ap = path.join(shell, 'adb.exe');
    if (!emu && fs.existsSync(ep) && fs.statSync(ep).isFile()) emu = ep;
    if (!adb && fs.existsSync(ap) && fs.statSync(ap).isFile()) adb = ap;
  }
  return { mumu_folder: folder, emu_path: emu, adb_path: adb };
}

/** 与 Electron installer:validate-path 一致：目录 / 文件需类型正确且真实存在 */
function pathIsValidForKey(key, p) {
  try {
    const s = String(p || '').trim();
    if (!s) return false;
    const n = path.normalize(s);
    if (!fs.existsSync(n)) return false;
    const st = fs.statSync(n);
    if (key === 'mumu_folder') return st.isDirectory();
    if (key === 'emu_path' || key === 'adb_path') return st.isFile();
    return true;
  } catch (_) {
    return false;
  }
}

function emulatorPathsNeedFill(emulator) {
  for (const k of ['mumu_folder', 'emu_path', 'adb_path']) {
    const v = String(emulator[k] || '');
    if (!v || v.startsWith('YOUR_')) return true;
    if (!pathIsValidForKey(k, v)) return true;
  }
  return false;
}

function adbSerial(adbPath) {
  try {
    execSync(`"${adbPath}" start-server`, { stdio: 'pipe', timeout: 8000 });
    const r = execSync(`"${adbPath}" devices`, { encoding: 'utf-8', timeout: 8000 });
    const lines = (r || '').split(/\r?\n/);
    for (const ln of lines) {
      if (ln.includes('\tdevice')) {
        const serial = ln.split('\t')[0].trim();
        if (serial.startsWith('127.0.0.1:')) return serial;
      }
    }
    for (const ln of lines) {
      if (ln.includes('\tdevice')) return ln.split('\t')[0].trim();
    }
  } catch (_) {}
  return null;
}

function applyMumuConfig(installRoot, send) {
  const cfgInData = path.join(installRoot, 'data', 'config.json');
  const cfgLegacy = path.join(installRoot, 'config.json');
  const cfgPath = fs.existsSync(cfgInData) ? cfgInData : cfgLegacy;
  let data = {};
  try {
    if (fs.existsSync(cfgPath)) {
      data = JSON.parse(fs.readFileSync(cfgPath, 'utf-8'));
    }
  } catch (_) {
    data = {};
  }
  const emulator = data.emulator || {};
  data.emulator = emulator;

  const need = emulatorPathsNeedFill(emulator);

  if (need) {
    const candidates = searchMumuFolders();
    send({ type: 'log', message: `[MuMu] 扫描到 ${candidates.length} 个候选目录` });
    let chosen = null;
    for (const c of candidates) {
      if (c.toLowerCase().includes('global')) continue;
      chosen = c;
      break;
    }
    if (chosen) {
      const paths = deriveFromFolder(chosen);
      const anyDerived = !!(paths.emu_path || paths.adb_path);
      if (!anyDerived) {
        send({
          type: 'log',
          message: `[MuMu] 目录 ${chosen} 下未找到 MuMuManager/MuMuPlayer 与 adb.exe，请在向导中手动选择有效路径`,
        });
      }
      for (const [k, v] of Object.entries(paths)) {
        if (!v) continue;
        const cur = String(emulator[k] || '');
        const curOk = cur && !cur.startsWith('YOUR_') && pathIsValidForKey(k, cur);
        if (!curOk) {
          emulator[k] = v;
        }
      }
      if (anyDerived) {
        send({ type: 'log', message: `[MuMu] 已自动填写: ${chosen}` });
      }
    } else {
      send({ type: 'log', message: '[MuMu] 未检测到安装目录，请稍后在向导中手动选择' });
    }
  }

  const adbPath = emulator.adb_path;
  let addr = String(emulator.adb_addr || '');
  if (adbPath && (!addr || addr.startsWith('YOUR_') || addr.endsWith(':0'))) {
    const serial = adbSerial(adbPath);
    if (serial) {
      emulator.adb_addr = serial;
      send({ type: 'log', message: `[ADB] 设备地址: ${serial}` });
    }
  }

  try {
    fs.writeFileSync(cfgPath, JSON.stringify(data, null, 2), 'utf-8');
  } catch (e) {
    send({ type: 'log', message: `[配置] 写入失败: ${e.message}` });
  }
}

/**
 * 对已填写的 emulator 配置做功能性验证（不仅是路径是否存在，还跑一下看能不能用）。
 * 返回结构化的检测报告，供安装向导 UI 展示。
 */
function validateMumuSetup(emulator) {
  const results = {
    mumu_folder: { exists: false, detail: '' },
    emu_path:    { exists: false, runnable: false, version: '', detail: '' },
    adb_path:    { exists: false, runnable: false, version: '', detail: '' },
    adb_device:  { connected: false, serial: '', detail: '' },
    overall:     false,
  };

  const folder = String(emulator.mumu_folder || '').trim();
  if (folder && fs.existsSync(folder)) {
    try {
      const st = fs.statSync(folder);
      if (st.isDirectory()) {
        const hasNxMain = fs.existsSync(path.join(folder, 'nx_main'));
        const hasShell = fs.existsSync(path.join(folder, 'shell'));
        results.mumu_folder.exists = true;
        if (hasNxMain || hasShell) {
          results.mumu_folder.detail = '目录结构正常' + (hasNxMain ? ' (nx_main)' : '') + (hasShell ? ' (shell)' : '');
        } else {
          results.mumu_folder.detail = '目录存在但未找到 nx_main 或 shell 子目录，可能不是有效的 MuMu 安装目录';
        }
      } else {
        results.mumu_folder.detail = '路径存在但不是目录';
      }
    } catch (e) {
      results.mumu_folder.detail = '访问失败: ' + e.message;
    }
  } else {
    results.mumu_folder.detail = folder ? '路径不存在' : '未配置';
  }

  const emuPath = String(emulator.emu_path || '').trim();
  if (emuPath && fs.existsSync(emuPath)) {
    try {
      if (fs.statSync(emuPath).isFile()) {
        results.emu_path.exists = true;
        try {
          const out = execSync(`"${emuPath}" -v 0 player -ld`, {
            encoding: 'utf-8', timeout: 8000, stdio: ['pipe', 'pipe', 'pipe'],
          });
          results.emu_path.runnable = true;
          results.emu_path.detail = '可执行，响应正常';
        } catch (runErr) {
          const stderr = (runErr.stderr || '').trim();
          const stdout = (runErr.stdout || '').trim();
          if (runErr.status !== undefined && runErr.status !== null) {
            results.emu_path.runnable = true;
            results.emu_path.detail = '可执行（返回码 ' + runErr.status + '）';
          } else if (stderr || stdout) {
            results.emu_path.runnable = true;
            results.emu_path.detail = '可执行，有输出';
          } else {
            results.emu_path.detail = '文件存在但执行超时或无响应';
          }
        }
      } else {
        results.emu_path.detail = '路径存在但不是文件';
      }
    } catch (e) {
      results.emu_path.detail = '访问失败: ' + e.message;
    }
  } else {
    results.emu_path.detail = emuPath ? '文件不存在' : '未配置';
  }

  const adbPath = String(emulator.adb_path || '').trim();
  if (adbPath && fs.existsSync(adbPath)) {
    try {
      if (fs.statSync(adbPath).isFile()) {
        results.adb_path.exists = true;
        try {
          const ver = execSync(`"${adbPath}" version`, {
            encoding: 'utf-8', timeout: 5000, stdio: ['pipe', 'pipe', 'pipe'],
          });
          results.adb_path.runnable = true;
          const m = (ver || '').match(/Android Debug Bridge version ([\d.]+)/);
          results.adb_path.version = m ? m[1] : '';
          results.adb_path.detail = m ? 'ADB ' + m[1] : '可执行，版本未知';
        } catch (runErr) {
          if (runErr.status !== undefined && runErr.status !== null) {
            results.adb_path.runnable = true;
            results.adb_path.detail = '可执行（返回码 ' + runErr.status + '）';
          } else {
            results.adb_path.detail = '文件存在但执行失败';
          }
        }
      } else {
        results.adb_path.detail = '路径存在但不是文件';
      }
    } catch (e) {
      results.adb_path.detail = '访问失败: ' + e.message;
    }
  } else {
    results.adb_path.detail = adbPath ? '文件不存在' : '未配置';
  }

  if (results.adb_path.runnable) {
    const serial = adbSerial(adbPath);
    if (serial) {
      results.adb_device.connected = true;
      results.adb_device.serial = serial;
      results.adb_device.detail = '已连接设备 ' + serial;
    } else {
      results.adb_device.detail = '未检测到已连接设备（模拟器可能未运行）';
    }
  } else {
    results.adb_device.detail = 'ADB 不可用，跳过设备检测';
  }

  results.overall = results.mumu_folder.exists
    && results.emu_path.exists && results.emu_path.runnable
    && results.adb_path.exists && results.adb_path.runnable;

  return results;
}

module.exports = { applyMumuConfig, validateMumuSetup };
