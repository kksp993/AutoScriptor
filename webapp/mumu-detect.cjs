'use strict';

/**
 * 与 services/installer/installer.py 中 MuMu 探测逻辑对齐的简化版（无 Python 时用于发行包）。
 */
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const COMMON_NAMES = [
  'Netease\\MuMu',
  'Netease\\MuMu Player 12',
  'MuMu',
  'MuMu Player 12',
];

function programFilesBases() {
  const bases = [];
  const pf = process.env.ProgramFiles || 'C:\\Program Files';
  const pf86 = process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)';
  bases.push(path.resolve(pf), path.resolve(pf86));
  for (let c = 65; c <= 90; c++) {
    const root = `${String.fromCharCode(c)}:\\`;
    try {
      if (fs.existsSync(root)) {
        bases.push(path.join(root, 'Program Files'));
        bases.push(path.join(root, 'Program Files (x86)'));
        bases.push(root);
      }
    } catch (_) {}
  }
  return [...new Set(bases)];
}

function searchMumuFolders() {
  const seen = new Set();
  const out = [];
  for (const base of programFilesBases()) {
    for (const name of COMMON_NAMES) {
      const p = path.join(base, name);
      try {
        if (fs.existsSync(p)) {
          const k = p.toLowerCase();
          if (!seen.has(k)) {
            seen.add(k);
            out.push(p);
          }
        }
      } catch (_) {}
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

module.exports = { applyMumuConfig };
