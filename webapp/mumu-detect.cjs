'use strict';

/**
 * 与 services/installer/installer.py 中 MuMu 探测逻辑对齐（无 Python 时用于发行包）。
 * 检测优先级：Windows 注册表 → 全盘符文件系统扫描。
 */
const fs = require('fs');
const path = require('path');
const { execFileSync, execSync } = require('child_process');

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
    execFileSync(adbPath, ['start-server'], { stdio: 'pipe', timeout: 8000, windowsHide: true });
    const r = execFileSync(adbPath, ['devices'], { encoding: 'utf-8', timeout: 8000, windowsHide: true });
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

function adbDeviceRows(adbPath) {
  try {
    execFileSync(adbPath, ['start-server'], { stdio: 'pipe', timeout: 8000, windowsHide: true });
    const r = execFileSync(adbPath, ['devices'], { encoding: 'utf-8', timeout: 8000, windowsHide: true });
    return (r || '')
      .split(/\r?\n/)
      .map((ln) => ln.trim())
      .filter((ln) => ln && !ln.toLowerCase().startsWith('list of devices'))
      .map((ln) => {
        const parts = ln.split(/\s+/);
        return { serial: parts[0] || '', state: parts[1] || '', raw: ln };
      })
      .filter((row) => row.serial);
  } catch (_) {
  return [];
  }
}

function parseMumuInfoPayload(text) {
  try {
    const data = JSON.parse(String(text || '').trim() || '{}');
    if (Array.isArray(data)) return data.filter((item) => item && typeof item === 'object');
    if (data && typeof data === 'object') {
      if ('index' in data) return [data];
      return Object.values(data).filter((item) => item && typeof item === 'object' && 'index' in item);
    }
  } catch (_) {}
  return [];
}

function mumuInfoRows(emuPath) {
  const p = String(emuPath || '').trim();
  if (!p || !fs.existsSync(p)) return [];
  try {
    const out = execFileSync(p, ['info', '-v', 'all'], {
      encoding: 'utf-8',
      timeout: 8000,
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    return parseMumuInfoPayload(out);
  } catch (_) {
    return [];
  }
}

function normalizeSerialHost(host) {
  const h = String(host || '').trim().toLowerCase();
  if (!h || h === 'localhost' || h === '::1') return '127.0.0.1';
  return h;
}

function splitSerial(serial) {
  const s = String(serial || '').trim();
  const m = s.match(/^(.+):(\d+)$/);
  if (!m) return null;
  return { host: normalizeSerialHost(m[1]), port: String(m[2]) };
}

function playerSerial(player) {
  if (!player || typeof player !== 'object') return '';
  const port = player.adb_port === undefined || player.adb_port === null ? '' : String(player.adb_port).trim();
  if (!port) return '';
  return `${normalizeSerialHost(player.adb_host_ip || '127.0.0.1')}:${port}`;
}

function playerIsRunning(player) {
  if (!player || typeof player !== 'object') return false;
  if (player.is_process_started === true || player.is_android_started === true) return true;
  const state = String(player.player_state || '').toLowerCase();
  return state.includes('start') || state.includes('running');
}

function sortPlayersForSelection(players) {
  return [...players].sort((a, b) => {
    const ar = playerIsRunning(a) ? 0 : 1;
    const br = playerIsRunning(b) ? 0 : 1;
    if (ar !== br) return ar - br;
    const am = a.is_main === true ? 0 : 1;
    const bm = b.is_main === true ? 0 : 1;
    if (am !== bm) return am - bm;
    return Number(a.index || 0) - Number(b.index || 0);
  });
}

function findPlayerBySerial(players, serial) {
  const target = splitSerial(serial);
  if (!target) return null;
  for (const player of players || []) {
    const ps = splitSerial(playerSerial(player));
    if (!ps) continue;
    if (ps.port !== target.port) continue;
    if (ps.host === target.host || ps.host === '127.0.0.1' || target.host === '127.0.0.1') {
      return player;
    }
  }
  return null;
}

function coercePlayerIndex(player) {
  if (!player || player.index === undefined || player.index === null) return null;
  const n = Number(player.index);
  return Number.isFinite(n) ? n : String(player.index);
}

function reconnectPlayerPorts(adbPath, players) {
  for (const player of sortPlayersForSelection(players || [])) {
    const serial = playerSerial(player);
    if (!serial || !playerIsRunning(player)) continue;
    reconnectAdbSerial(adbPath, serial);
  }
}

function chooseAdbDevice(adbPath, emuPath, preferredSerial, opts = {}) {
  const allowFallback = opts.allowFallback !== false;
  const players = mumuInfoRows(emuPath);
  const preferred = String(preferredSerial || '').trim();

  if (preferred && !preferred.startsWith('YOUR_') && !preferred.endsWith(':0')) {
    let state = adbState(adbPath, preferred);
    if (!state.ok && preferred.includes(':')) {
      reconnectAdbSerial(adbPath, preferred);
      state = adbState(adbPath, preferred);
    }
    const player = findPlayerBySerial(players, preferred);
    if (state.ok) {
      return {
        connected: true,
        serial: preferred,
        detail: '配置设备已连接 ' + preferred,
        fallbackSerial: '',
        player,
        index: coercePlayerIndex(player),
      };
    }
    if (!allowFallback) {
      const fallbackRows = adbDeviceRows(adbPath).filter((row) => row.state === 'device');
      const fallback = fallbackRows.find((row) => row.serial.startsWith('127.0.0.1:')) || fallbackRows[0] || null;
      const extra = fallback
        ? `；另检测到 ${fallback.serial} 可用，但运行时会优先使用配置地址`
        : '';
      return {
        connected: false,
        serial: preferred,
        detail: `配置设备 ${preferred} 未连接${extra}。${state.detail || ''}`.trim(),
        fallbackSerial: fallback ? fallback.serial : '',
        player,
        index: coercePlayerIndex(player),
      };
    }
  }

  reconnectPlayerPorts(adbPath, players);
  const rows = adbDeviceRows(adbPath).filter((row) => row.state === 'device');
  let chosen = null;
  let player = null;
  for (const candidate of sortPlayersForSelection(players)) {
    const serial = playerSerial(candidate);
    if (!serial) continue;
    chosen = rows.find((row) => !!findPlayerBySerial([candidate], row.serial));
    if (chosen) {
      player = candidate;
      break;
    }
  }
  if (!chosen) {
    chosen = rows.find((row) => row.serial.startsWith('127.0.0.1:')) || rows[0] || null;
    player = chosen ? findPlayerBySerial(players, chosen.serial) : null;
  }
  if (chosen) {
    return {
      connected: true,
      serial: chosen.serial,
      detail: '已连接设备 ' + chosen.serial,
      fallbackSerial: '',
      player,
      index: coercePlayerIndex(player),
    };
  }

  return {
    connected: false,
    serial: preferred || '',
    detail: '未检测到已连接设备（模拟器可能未运行）',
    fallbackSerial: '',
    player: preferred ? findPlayerBySerial(players, preferred) : null,
    index: null,
  };
}

function adbState(adbPath, serial) {
  const s = String(serial || '').trim();
  if (!s || s.startsWith('YOUR_') || s.endsWith(':0')) {
    return { ok: false, state: '', detail: '未配置 ADB 设备地址' };
  }
  try {
    const out = execFileSync(adbPath, ['-s', s, 'get-state'], {
      encoding: 'utf-8',
      timeout: 5000,
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
    }).trim();
    return { ok: out === 'device', state: out, detail: out ? `state=${out}` : 'get-state 无输出' };
  } catch (e) {
    const detail = String((e.stderr || e.stdout || e.message || '')).trim();
    return { ok: false, state: '', detail: detail || 'get-state failed' };
  }
}

function reconnectAdbSerial(adbPath, serial) {
  const s = String(serial || '').trim();
  if (!s || !s.includes(':') || s.startsWith('YOUR_') || s.endsWith(':0')) return false;
  try {
    execFileSync(adbPath, ['disconnect', s], { encoding: 'utf-8', timeout: 5000, windowsHide: true });
  } catch (_) {}
  try {
    execFileSync(adbPath, ['connect', s], { encoding: 'utf-8', timeout: 8000, windowsHide: true });
    return true;
  } catch (_) {
    return false;
  }
}

function checkConfiguredAdbDevice(adbPath, preferredSerial) {
  const serial = String(preferredSerial || '').trim();
  const rows = adbDeviceRows(adbPath);
  const usableRows = rows.filter((row) => row.state === 'device');
  const fallback = usableRows.find((row) => row.serial.startsWith('127.0.0.1:')) || usableRows[0] || null;
  if (!serial || serial.startsWith('YOUR_') || serial.endsWith(':0')) {
    return fallback
      ? { connected: true, serial: fallback.serial, detail: '已连接设备 ' + fallback.serial, fallbackSerial: '' }
      : { connected: false, serial: '', detail: '未检测到已连接设备（模拟器可能未运行）', fallbackSerial: '' };
  }

  let state = adbState(adbPath, serial);
  if (!state.ok && serial.includes(':')) {
    reconnectAdbSerial(adbPath, serial);
    state = adbState(adbPath, serial);
  }
  if (state.ok) {
    return { connected: true, serial, detail: '配置设备已连接 ' + serial, fallbackSerial: '' };
  }

  const row = rows.find((item) => item.serial === serial);
  const rowState = row ? row.state : '';
  const detail = rowState
    ? `配置设备 ${serial} 状态为 ${rowState}`
    : `配置设备 ${serial} 未连接`;
  const fallbackText = fallback
    ? `；另检测到 ${fallback.serial} 可用，但运行时会优先使用配置地址`
    : '';
  return {
    connected: false,
    serial,
    detail: `${detail}${fallbackText}。${state.detail || ''}`.trim(),
    fallbackSerial: fallback ? fallback.serial : '',
  };
}

function clonePlain(obj) {
  return JSON.parse(JSON.stringify(obj || {}));
}

function previewMumuConfig(configData, opts = {}) {
  const data = clonePlain(configData);
  const emulator = data.emulator || {};
  data.emulator = emulator;

  const report = {
    candidates: 0,
    chosen: '',
    changed: false,
    emulator: {
      index: emulator.index,
      mumu_folder: String(emulator.mumu_folder || ''),
      emu_path: String(emulator.emu_path || ''),
      adb_path: String(emulator.adb_path || ''),
      adb_addr: String(emulator.adb_addr || ''),
    },
    pathStatus: {
      mumu_folder: pathIsValidForKey('mumu_folder', emulator.mumu_folder),
      emu_path: pathIsValidForKey('emu_path', emulator.emu_path),
      adb_path: pathIsValidForKey('adb_path', emulator.adb_path),
    },
    willNeedManualPaths: false,
    willNeedRunningDevice: false,
    adbDevice: null,
  };

  const before = JSON.stringify(report.emulator);
  if (emulatorPathsNeedFill(emulator)) {
    const candidates = searchMumuFolders();
    report.candidates = candidates.length;
    let chosen = null;
    for (const c of candidates) {
      if (c.toLowerCase().includes('global')) continue;
      chosen = c;
      break;
    }
    if (chosen) {
      report.chosen = chosen;
      const paths = deriveFromFolder(chosen);
      for (const [k, v] of Object.entries(paths)) {
        if (!v) continue;
        const cur = String(emulator[k] || '');
        const curOk = cur && !cur.startsWith('YOUR_') && pathIsValidForKey(k, cur);
        if (!curOk) emulator[k] = v;
      }
    }
  }

  if (opts.probeAdb && emulator.adb_path) {
    const addr = String(emulator.adb_addr || '');
    const needsAddr = !addr || addr.startsWith('YOUR_') || addr.endsWith(':0');
    const device = chooseAdbDevice(emulator.adb_path, emulator.emu_path, addr, { allowFallback: needsAddr });
    if (device.connected && (needsAddr || device.serial === addr)) {
      emulator.adb_addr = device.serial;
      if (device.index !== null && device.index !== undefined) emulator.index = device.index;
    }
  }

  report.emulator = {
    index: emulator.index,
    mumu_folder: String(emulator.mumu_folder || ''),
    emu_path: String(emulator.emu_path || ''),
    adb_path: String(emulator.adb_path || ''),
    adb_addr: String(emulator.adb_addr || ''),
  };
  report.pathStatus = {
    mumu_folder: pathIsValidForKey('mumu_folder', emulator.mumu_folder),
    emu_path: pathIsValidForKey('emu_path', emulator.emu_path),
    adb_path: pathIsValidForKey('adb_path', emulator.adb_path),
  };
  report.changed = before !== JSON.stringify(report.emulator);
  report.willNeedManualPaths = !(
    report.pathStatus.mumu_folder
    && report.pathStatus.emu_path
    && report.pathStatus.adb_path
  );
  const addr = report.emulator.adb_addr;
  report.willNeedRunningDevice = !addr || addr.startsWith('YOUR_') || addr.endsWith(':0');
  if (opts.probeAdb && emulator.adb_path) {
    const device = checkConfiguredAdbDevice(emulator.adb_path, addr);
    report.adbDevice = device;
    report.willNeedRunningDevice = !device.connected;
  }
  return report;
}

function applyMumuConfig(installRoot, send, opts = {}) {
  const dataRoot = opts && opts.dataRoot ? path.resolve(String(opts.dataRoot)) : path.join(installRoot, 'data');
  const cfgInData = path.join(dataRoot, 'config.json');
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
  const needsAddr = !addr || addr.startsWith('YOUR_') || addr.endsWith(':0');
  if (adbPath) {
    const device = chooseAdbDevice(adbPath, emulator.emu_path, addr, { allowFallback: needsAddr });
    if (device.connected && (needsAddr || device.serial === addr)) {
      emulator.adb_addr = device.serial;
      addr = device.serial;
      send({ type: 'log', message: `[ADB] ${needsAddr ? '设备地址' : '配置设备已连接'}: ${device.serial}` });
      if (device.index !== null && device.index !== undefined) {
        const beforeIndex = emulator.index;
        emulator.index = device.index;
        if (String(beforeIndex) !== String(device.index)) {
          send({ type: 'log', message: `[MuMu] 已根据 ADB 端口同步实例序号: ${device.index}` });
        }
      }
    } else if (device.index !== null && device.index !== undefined && addr && !addr.startsWith('YOUR_')) {
      const beforeIndex = emulator.index;
      emulator.index = device.index;
      if (String(beforeIndex) !== String(device.index)) {
        send({ type: 'log', message: `[MuMu] 已根据配置 ADB 地址同步实例序号: ${device.index}` });
      }
      send({ type: 'log', message: `[ADB] ${device.detail}` });
    } else if (needsAddr) {
      const serial = adbSerial(adbPath);
      if (serial) {
        emulator.adb_addr = serial;
        send({ type: 'log', message: `[ADB] 设备地址: ${serial}` });
      } else {
        send({ type: 'log', message: `[ADB] ${device.detail}` });
      }
    } else {
      send({ type: 'log', message: `[ADB] ${device.detail}` });
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
    emulator_index: { configured: emulator.index, detected: null, match: null, detail: '' },
    overall:     false,
    operationReady: false,
    needsRunningDevice: false,
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
          const out = execSync(`"${emuPath}" version`, {
            encoding: 'utf-8', timeout: 8000, stdio: ['pipe', 'pipe', 'pipe'],
          });
          results.emu_path.runnable = true;
          let ver = '';
          try {
            ver = JSON.parse(out || '{}').version || '';
          } catch (_) {}
          results.emu_path.version = ver;
          results.emu_path.detail = ver ? `可执行（MuMuManager ${ver}）` : '可执行，响应正常';
        } catch (runErr) {
          const stderr = (runErr.stderr || '').trim();
          const stdout = (runErr.stdout || '').trim();
          const code = runErr.status !== undefined && runErr.status !== null ? runErr.status : 'timeout';
          const hint = (stderr || stdout || '').split(/\r?\n/)[0] || '';
          results.emu_path.runnable = false;
          results.emu_path.detail = 'MuMuManager version 失败（返回码 ' + code + '）。' +
            '若 ADB 可用，安装器会继续；后续可在 WebUI「启动诊断」确认。' +
            (hint ? ' ' + hint : '');
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
    const addr = String(emulator.adb_addr || '');
    const needsAddr = !addr || addr.startsWith('YOUR_') || addr.endsWith(':0');
    const device = chooseAdbDevice(adbPath, emuPath, addr, { allowFallback: needsAddr });
    results.adb_device.connected = device.connected;
    results.adb_device.serial = device.serial;
    results.adb_device.detail = device.detail;
    if (device.fallbackSerial) results.adb_device.fallback_serial = device.fallbackSerial;
    results.emulator_index.detected = device.index;
    const configured = emulator.index === undefined || emulator.index === null ? '' : String(emulator.index);
    const detected = device.index === undefined || device.index === null ? '' : String(device.index);
    if (detected) {
      results.emulator_index.match = !configured || configured === detected;
      results.emulator_index.detail = results.emulator_index.match
        ? `ADB 地址对应 MuMu 实例 ${detected}`
        : `配置 index=${configured}，但 ADB 地址 ${device.serial} 对应 MuMu 实例 ${detected}`;
    } else {
      results.emulator_index.match = null;
      results.emulator_index.detail = '未能从 MuMuManager info 反查 ADB 地址对应的实例序号';
    }
  } else {
    results.adb_device.detail = 'ADB 不可用，跳过设备检测';
  }

  if (results.emu_path.exists && !results.emu_path.runnable) {
    if (results.adb_device.connected) {
      results.emu_path.detail += ' 已检测到 ADB 设备可用，安装器将把 MuMuManager 异常视为警告。';
    } else if (results.adb_path.runnable) {
      results.emu_path.detail += ' ADB 可执行文件可用，安装器将把 MuMuManager 异常视为警告。';
    }
  }

  results.overall = results.mumu_folder.exists
    && results.emu_path.exists
    && results.adb_path.exists && results.adb_path.runnable;
  results.operationReady = results.overall && results.adb_device.connected;
  if (results.operationReady && results.emulator_index.match === false) {
    results.operationReady = false;
    results.adb_device.detail += '；MuMu 实例序号与 ADB 地址不一致，请重新运行安装器配置或在设置中修正 index';
  }
  results.needsRunningDevice = results.overall && !results.adb_device.connected;

  return results;
}

module.exports = {
  applyMumuConfig,
  validateMumuSetup,
  previewMumuConfig,
  __test: {
    parseMumuInfoPayload,
    findPlayerBySerial,
    playerSerial,
    chooseAdbDevice,
  },
};
