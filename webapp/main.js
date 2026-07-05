'use strict';

const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain, shell, globalShortcut } = require('electron');
const { spawn, execFileSync } = require('child_process');
const treeKill = require('tree-kill');
const path = require('path');
const http = require('http');
const fs = require('fs');

const startupProcessStartedAt = Date.now();
const SERVER_URL = 'http://127.0.0.1:5000';
const BOSS_KEY = 'Alt+W';
const ROOT = path.resolve(__dirname, '..');
const ICON_PATH = path.join(__dirname, 'icon.ico');
const ICON_PNG = path.join(__dirname, 'icon.png');
const LOAD_HTML = path.join(__dirname, 'renderer', 'loading.html');
const ELECTRON_RENDER_MODE_ENV = 'AUTOSCRIPTOR_ELECTRON_RENDER_MODE';
const DEFAULT_ELECTRON_RENDER_MODE = 'software';
const ELECTRON_RENDER_MODES = new Set([DEFAULT_ELECTRON_RENDER_MODE, 'd3d11', 'default']);
const SOFTWARE_RENDER_SWITCHES = [
  'disable-gpu',
  'disable-gpu-compositing',
  'disable-gpu-rasterization',
  'disable-zero-copy',
  'disable-accelerated-2d-canvas',
  'disable-accelerated-video-decode',
];

let mainWindow = null;
let tray = null;
let pyProc = null;
let pyPid = null;
let serverReady = false;
let quitStarted = false;

const LOG_BUFFER_MAX = 500;
const logBuffer = [];
let loadingScreenLogFlushDone = false;
let pendingStatus = null;
const startupTimers = new Map();
let startupPhase = '';
let startupPhaseStartedAt = 0;

function startupLog(message, detail) {
  try {
    const line = `[${new Date().toISOString()}] ${message}${detail ? ` ${detail}` : ''}\n`;
    const logPath = path.join(app.getPath('userData'), 'startup.log');
    fs.mkdirSync(path.dirname(logPath), { recursive: true });
    fs.appendFileSync(logPath, line, 'utf8');
  } catch (_) {}
}

process.on('uncaughtException', (err) => {
  startupLog('uncaughtException', err && err.stack ? err.stack : String(err));
  throw err;
});

process.on('unhandledRejection', (err) => {
  startupLog('unhandledRejection', err && err.stack ? err.stack : String(err));
});

function normalizeElectronRenderMode(value) {
  const mode = String(value || '').trim().toLowerCase();
  return ELECTRON_RENDER_MODES.has(mode) ? mode : DEFAULT_ELECTRON_RENDER_MODE;
}

const requestedElectronRenderMode = String(process.env[ELECTRON_RENDER_MODE_ENV] || '').trim().toLowerCase();
const electronRenderMode = normalizeElectronRenderMode(requestedElectronRenderMode);

function appendChromiumSwitches(switches) {
  for (const switchName of switches) {
    app.commandLine.appendSwitch(switchName);
  }
}

function configureElectronRendering() {
  if (requestedElectronRenderMode && requestedElectronRenderMode !== electronRenderMode) {
    startupLog(
      'electron-render-mode-invalid',
      `${ELECTRON_RENDER_MODE_ENV}=${requestedElectronRenderMode}; fallback=${electronRenderMode}`,
    );
  }

  if (electronRenderMode === 'software') {
    app.disableHardwareAcceleration();
    appendChromiumSwitches(SOFTWARE_RENDER_SWITCHES);
    startupLog(
      'electron-render-mode',
      `mode=${electronRenderMode} hardwareAcceleration=false switches=${SOFTWARE_RENDER_SWITCHES.join(',')}`,
    );
    return;
  }

  if (electronRenderMode === 'd3d11') {
    app.commandLine.appendSwitch('use-angle', 'd3d11');
    startupLog('electron-render-mode', `mode=${electronRenderMode} switches=use-angle=d3d11`);
    return;
  }

  startupLog('electron-render-mode', `mode=${electronRenderMode} switches=none`);
}

configureElectronRendering();

function logElectronGpuStatus() {
  sendToRenderer('log', `[startup] Electron render mode: ${electronRenderMode}`);
  try {
    const status = app.getGPUFeatureStatus();
    const detail = JSON.stringify(status || {});
    startupLog('electron-gpu-status', detail);
    console.log('[main] Electron GPU status:', detail);
    sendToRenderer('log', `[startup] Electron GPU status: ${detail}`);
  } catch (err) {
    const message = err && err.message ? err.message : String(err);
    startupLog('electron-gpu-status-failed', message);
    console.warn('[main] Electron GPU status failed:', message);
    sendToRenderer('log', `[warning] Electron GPU status failed: ${message}`);
  }
}

function getRoot() {
  return ROOT;
}

function guiScriptPath() {
  return path.join(getRoot(), 'services', 'webui', 'gui.py');
}

function browserWindowWebPreferences() {
  return {
    preload: path.join(__dirname, 'preload.js'),
    nodeIntegration: false,
    contextIsolation: true,
    sandbox: false,
  };
}

function loadAppIcon() {
  if (fs.existsSync(ICON_PATH)) return nativeImage.createFromPath(ICON_PATH);
  if (fs.existsSync(ICON_PNG)) return nativeImage.createFromPath(ICON_PNG);
  return undefined;
}

function loadTrayIcon() {
  const base = loadAppIcon();
  if (!base || base.isEmpty()) return undefined;
  try {
    return base.resize({ width: 16, height: 16 });
  } catch (_) {
    return base;
  }
}

function findPython() {
  const binName = process.platform === 'win32' ? 'python.exe' : 'python';
  const candidate = path.join(getRoot(), '.venv', process.platform === 'win32' ? 'Scripts' : 'bin', binName);
  return fs.existsSync(candidate) ? candidate : null;
}

function createLineReader(onLine) {
  let buf = Buffer.alloc(0);
  return (chunk) => {
    buf = Buffer.concat([buf, chunk]);
    let start = 0;
    for (let i = 0; i < buf.length; i++) {
      if (buf[i] === 0x0A) {
        let end = i;
        if (end > start && buf[end - 1] === 0x0D) end--;
        onLine(buf.slice(start, end).toString('utf8'));
        start = i + 1;
      }
    }
    buf = buf.slice(start);
  };
}

function startupElapsedMs() {
  return Date.now() - startupProcessStartedAt;
}

function formatElapsed(ms) {
  return `${(Math.max(0, ms) / 1000).toFixed(1)}s`;
}

function reportStartupStep(status, message, detail) {
  startupPhase = status || startupPhase;
  startupPhaseStartedAt = Date.now();
  const line = `[startup] ${message}${detail ? `: ${detail}` : ''} (${formatElapsed(startupElapsedMs())})`;
  startupLog(status || 'startup-step', `${message}${detail ? ` ${detail}` : ''}`);
  console.log('[main]', line);
  sendToRenderer('status', status || 'starting');
  sendToRenderer('log', line);
}

function clearStartupTimer(name) {
  const timer = startupTimers.get(name);
  if (timer) clearTimeout(timer);
  startupTimers.delete(name);
}

function scheduleStartupTimer(name, delayMs, message) {
  clearStartupTimer(name);
  startupTimers.set(name, setTimeout(() => {
    startupTimers.delete(name);
    if (serverReady || app.isQuitting || quitStarted) return;
    const phaseSeconds = startupPhaseStartedAt ? formatElapsed(Date.now() - startupPhaseStartedAt) : '0.0s';
    sendToRenderer('log', `[startup] ${message}; phase=${startupPhase || 'unknown'} elapsed=${phaseSeconds}`);
  }, delayMs));
}

function clearStartupTimers() {
  for (const timer of startupTimers.values()) clearTimeout(timer);
  startupTimers.clear();
}

function sendToRenderer(channel, data) {
  if (channel === 'log') {
    const line = String(data);
    logBuffer.push(line);
    if (logBuffer.length > LOG_BUFFER_MAX) logBuffer.shift();
    if (mainWindow && !mainWindow.isDestroyed() && loadingScreenLogFlushDone) {
      mainWindow.webContents.send('log', line);
    }
    return;
  }

  if (channel === 'status') {
    pendingStatus = data;
    if (mainWindow && !mainWindow.isDestroyed() && loadingScreenLogFlushDone) {
      mainWindow.webContents.send('status', data);
    }
    return;
  }

  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.send(channel, data);
}

function flushLoadingScreenIpc() {
  if (!mainWindow || mainWindow.isDestroyed() || loadingScreenLogFlushDone) return;
  loadingScreenLogFlushDone = true;
  if (pendingStatus != null) {
    mainWindow.webContents.send('status', pendingStatus);
  }
  for (const line of logBuffer) {
    mainWindow.webContents.send('log', line);
  }
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  startupLog('single-instance-lock-denied');
  app.quit();
} else {
  startupLog('single-instance-lock-acquired');
  app.on('second-instance', () => {
    startupLog('second-instance');
    showMainWindow();
  });
}

function psQuote(value) {
  return `'${String(value).replace(/'/g, "''")}'`;
}

function normalizeRootForMatch(root) {
  const s = String(root || '').trim();
  if (s.length < 4) return null;
  const r = path.resolve(s);
  return r.endsWith(path.sep) ? r : r + path.sep;
}

function autoScriptorKillRoots(extraRoots = []) {
  const roots = new Set();
  const add = (r) => {
    const n = normalizeRootForMatch(r);
    if (n) roots.add(n);
  };
  add(getRoot());
  add(path.join(getRoot(), 'backend'));
  add(path.dirname(process.execPath));
  for (const r of extraRoots || []) add(r);
  return [...roots];
}

function killAutoScriptorProcessResidue(extraRoots = []) {
  if (process.platform !== 'win32') return;
  const roots = autoScriptorKillRoots(extraRoots);
  if (roots.length === 0) return;

  const ps = `
$ownPid = ${process.pid}
$roots = @(${roots.map(psQuote).join(',')})
Get-CimInstance Win32_Process | ForEach-Object {
  try {
    $pidValue = [int]$_.ProcessId
    if ($pidValue -eq $ownPid) { return }
    $exe = [string]$_.ExecutablePath
    $cmd = [string]$_.CommandLine
    $owned = $false
    foreach ($r in $roots) {
      if ($exe -and $exe.StartsWith($r, [System.StringComparison]::OrdinalIgnoreCase)) { $owned = $true; break }
      if ($cmd -and $cmd.IndexOf($r, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) { $owned = $true; break }
    }
    if ($owned) {
      & taskkill.exe /PID $pidValue /T /F 2>$null 1>$null
      Write-Output ("killed:" + $pidValue + ":" + $_.Name)
    }
  } catch {
    Write-Output ("error:" + $_.ProcessId + ":" + $_.Exception.Message)
  }
}
`;
  try {
    const result = execFileSync(
      'powershell.exe',
      ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps],
      { encoding: 'utf8', windowsHide: true, timeout: 30000 },
    );
    for (const line of String(result || '').split(/\r?\n/).filter(Boolean)) {
      console.log('[main] process cleanup:', line);
    }
  } catch (err) {
    console.warn('[main] Process cleanup failed:', err && err.message ? err.message : String(err));
  }
}

function killStalePort5000(extraRoots = []) {
  if (process.platform !== 'win32') return;
  try {
    const output = execFileSync('netstat.exe', ['-ano'], { encoding: 'utf8', timeout: 5000, windowsHide: true });
    const pids = new Set();
    for (const line of output.split('\n')) {
      if (line.includes(':5000') && line.includes('LISTENING')) {
        const parts = line.trim().split(/\s+/);
        const pid = parseInt(parts[parts.length - 1], 10);
        if (pid > 0 && pid !== process.pid) pids.add(pid);
      }
    }
    if (pids.size === 0) return;

    const roots = autoScriptorKillRoots(extraRoots);
    if (roots.length === 0) {
      console.warn('[main] Port 5000 is occupied, but no AutoScriptor root is known; leaving it alone.');
      return;
    }

    const ps = `
$pids = @(${[...pids].join(',')})
$roots = @(${roots.map(psQuote).join(',')})
foreach ($pidValue in $pids) {
  try {
    $proc = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $pidValue)
    if (-not $proc) { continue }
    $exe = [string]$proc.ExecutablePath
    $cmd = [string]$proc.CommandLine
    $owned = $false
    foreach ($r in $roots) {
      if ($exe -and $exe.StartsWith($r, [System.StringComparison]::OrdinalIgnoreCase)) { $owned = $true; break }
      if ($cmd -and $cmd.IndexOf($r, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) { $owned = $true; break }
    }
    if ($owned) {
      & taskkill.exe /PID $pidValue /T /F 2>$null 1>$null
      Write-Output ("killed:" + $pidValue)
    } else {
      Write-Output ("skipped:" + $pidValue + ":" + $exe)
    }
  } catch {
    Write-Output ("error:" + $pidValue + ":" + $_.Exception.Message)
  }
}
`;
    const result = execFileSync(
      'powershell.exe',
      ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps],
      { encoding: 'utf8', windowsHide: true, timeout: 30000 },
    );
    for (const line of String(result || '').split(/\r?\n/).filter(Boolean)) {
      console.log('[main] port5000 cleanup:', line);
    }
  } catch (err) {
    const message = err && err.message ? err.message : String(err);
    startupLog('port5000-cleanup-failed', message);
    console.warn('[main] Port 5000 cleanup failed:', message);
    sendToRenderer('log', `[warning] Port 5000 cleanup failed: ${message}`);
  }
}

function maybeNotifyServerReady(line) {
  if (line.includes('Application startup complete') || line.includes('Uvicorn running on')) {
    if (!serverReady) {
      serverReady = true;
      clearStartupTimers();
      reportStartupStep('webui-ready', 'Backend reported startup complete');
      pollServer();
    }
  }
}

function attachBackendProcessHandlers() {
  pyProc.stdout.on('data', createLineReader(line => {
    clearStartupTimer('backend-no-output-5s');
    clearStartupTimer('backend-no-output-15s');
    console.log('[backend]', line);
    sendToRenderer('log', line);
    maybeNotifyServerReady(line);
  }));

  pyProc.stderr.on('data', createLineReader(line => {
    clearStartupTimer('backend-no-output-5s');
    clearStartupTimer('backend-no-output-15s');
    console.log('[backend:err]', line);
    sendToRenderer('log', line);
    maybeNotifyServerReady(line);
  }));

  pyProc.on('error', err => {
    console.error('[backend:error]', err);
    sendToRenderer('log', String(err));
    clearStartupTimers();
  });

  pyProc.on('spawn', () => {
    pyPid = pyProc.pid;
    console.log('[main] Backend PID:', pyPid);
    reportStartupStep('backend-spawned', 'Backend process created', `pid=${pyPid}`);
    scheduleStartupTimer('backend-no-output-5s', 5000, 'Python is importing dependencies');
    scheduleStartupTimer('backend-no-output-15s', 15000, 'Backend is still starting');
    setTimeout(() => { if (!serverReady) pollServer(); }, 8000);
  });

  pyProc.on('exit', (code) => {
    console.log('[backend] exited with code', code);
    clearStartupTimers();
    if (!app.isQuitting) {
      sendToRenderer('log', `[backend exited code=${code}]`);
    }
  });
}

function startPython() {
  const guiScript = guiScriptPath();
  reportStartupStep('starting-backend', 'Preparing source backend');
  if (!fs.existsSync(guiScript)) {
    const msg = `Missing backend entry: ${guiScript}`;
    console.error('[main]', msg);
    sendToRenderer('log', `[error] ${msg}`);
    return;
  }

  const pythonPath = findPython();
  if (!pythonPath) {
    const msg = `Missing source Python venv: ${path.join(getRoot(), '.venv')}. Run scripts\\install.bat python first.`;
    console.error('[main]', msg);
    sendToRenderer('log', `[error] ${msg}`);
    return;
  }

  console.log('[main] Starting Python:', pythonPath, guiScript);
  startupLog('starting-source-python', `${pythonPath} ${guiScript}`);
  reportStartupStep('starting-python', 'Starting source Python backend', pythonPath);

  const backendEnv = {
    ...process.env,
    PYTHONIOENCODING: 'utf-8',
    PYTHONUTF8: '1',
    AUTOSCRIPTOR_ELECTRON_PIPE: '1',
    AUTOSCRIPTOR_ELECTRON: '1',
    NO_COLOR: '1',
  };
  delete backendEnv.ELECTRON_RUN_AS_NODE;

  pyProc = spawn(
    pythonPath,
    ['-X', 'utf8', '-u', guiScript, '--electron'],
    {
      cwd: getRoot(),
      stdio: ['ignore', 'pipe', 'pipe'],
      env: backendEnv,
    },
  );
  attachBackendProcessHandlers();
}

function pollServer(retries = 0) {
  if (retries > 90) {
    sendToRenderer('log', '[error] WebUI startup timed out; check backend logs');
    return;
  }
  if (retries === 0) {
    reportStartupStep('waiting-webui', 'Connecting to local WebUI', SERVER_URL);
  } else if (retries % 5 === 0) {
    sendToRenderer('log', `[startup] WebUI is still preparing, waited about ${retries}s`);
  }

  const req = http.get(SERVER_URL, (res) => {
    let body = '';
    res.on('data', d => { body += d; });
    res.on('end', () => {
      if (res.statusCode === 200 && (body.includes('AutoScriptor') || body.includes('造笔'))) {
        console.log('[main] Server ready, loading app...');
        clearStartupTimers();
        reportStartupStep('ready', 'WebUI responded; loading app');
        sendToRenderer('status', 'ready');
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.loadURL(SERVER_URL);
        }
      } else {
        setTimeout(() => pollServer(retries + 1), 1000);
      }
    });
  });
  req.on('error', () => {
    setTimeout(() => pollServer(retries + 1), 1000);
  });
  req.setTimeout(2000, () => {
    req.destroy();
    setTimeout(() => pollServer(retries + 1), 1000);
  });
}

function showMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  if (!mainWindow.isVisible()) mainWindow.show();
  mainWindow.focus();
  refreshTrayMenu();
}

function hideMainWindowToTray() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.hide();
  refreshTrayMenu();
}

function toggleMainWindowToTray() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isVisible() && !mainWindow.isMinimized()) {
    hideMainWindowToTray();
    return;
  }
  showMainWindow();
}

function openMainWindowDevTools() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  showMainWindow();
  mainWindow.webContents.openDevTools({ mode: 'detach' });
}

function createMainWindow() {
  const icon = loadAppIcon();
  startupLog('create-main-window');

  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    show: false,
    icon,
    title: 'AutoScriptor',
    webPreferences: browserWindowWebPreferences(),
  });

  mainWindow.once('ready-to-show', () => {
    startupLog('main-window-ready-to-show');
    mainWindow.show();
    reportStartupStep('window-visible', 'Startup window is visible');
  });

  mainWindow.webContents.on('console-message', (_e, level, msg, line, src) => {
    const tag = ['V', 'I', 'W', 'E'][level] || 'L';
    console.log(`[renderer:${tag}] ${msg} (${src}:${line})`);
  });

  loadingScreenLogFlushDone = false;
  mainWindow.webContents.once('did-finish-load', () => {
    flushLoadingScreenIpc();
  });
  mainWindow.loadFile(LOAD_HTML);

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      quitApp();
    }
  });

  return mainWindow;
}

function buildTrayMenu() {
  const windowVisible = !!(mainWindow && !mainWindow.isDestroyed() && mainWindow.isVisible() && !mainWindow.isMinimized());
  return Menu.buildFromTemplate([
    {
      label: `${windowVisible ? 'Hide AutoScriptor' : 'Show AutoScriptor'} (${BOSS_KEY})`,
      click: () => toggleMainWindowToTray(),
    },
    { type: 'separator' },
    { label: 'Open in browser', click: () => shell.openExternal(SERVER_URL) },
    { label: 'Open DevTools', click: () => openMainWindowDevTools() },
    { type: 'separator' },
    { label: 'Quit', click: () => quitApp() },
  ]);
}

function refreshTrayMenu() {
  if (!tray || (typeof tray.isDestroyed === 'function' && tray.isDestroyed())) return;
  tray.setContextMenu(buildTrayMenu());
}

function createTray() {
  const icon = loadTrayIcon() || nativeImage.createEmpty();
  tray = new Tray(icon);
  tray.setToolTip('AutoScriptor');
  refreshTrayMenu();
  tray.on('click', () => {
    toggleMainWindowToTray();
    refreshTrayMenu();
  });
  tray.on('right-click', () => tray.popUpContextMenu(buildTrayMenu()));
}

function registerBossKey() {
  globalShortcut.unregister(BOSS_KEY);
  const ok = globalShortcut.register(BOSS_KEY, () => {
    toggleMainWindowToTray();
  });
  if (!ok) {
    console.warn(`[main] Failed to register boss key: ${BOSS_KEY}`);
  }
}

ipcMain.on('window-tray', () => {
  mainWindow?.hide();
});

ipcMain.on('window-minimize', () => {
  mainWindow?.minimize();
});

ipcMain.on('window-close', () => {
  quitApp();
});

function finishQuit() {
  pyPid = null;
  pyProc = null;
  killStalePort5000();
  killAutoScriptorProcessResidue();
  setTimeout(() => {
    tray?.destroy();
    app.quit();
  }, 300);
}

function quitApp() {
  if (quitStarted) return;
  quitStarted = true;
  app.isQuitting = true;

  if (pyPid) {
    const pid = pyPid;
    treeKill(pid, 'SIGTERM', (err) => {
      if (err) console.error('[main] treeKill:', err);
      finishQuit();
    });
    return;
  }
  if (pyProc) {
    try { pyProc.kill(); } catch (_) {}
  }
  finishQuit();
}

app.whenReady().then(() => {
  app.isQuitting = false;
  startupLog('app-ready', `argv=${JSON.stringify(process.argv)} exec=${process.execPath} renderMode=${electronRenderMode}`);
  logElectronGpuStatus();
  reportStartupStep('electron-ready', 'Electron runtime is ready', `render=${electronRenderMode}`);
  reportStartupStep('creating-window', 'Creating startup window', getRoot());
  createMainWindow();
  createTray();
  registerBossKey();
  setTimeout(() => {
    reportStartupStep('checking-port', 'Checking local port 5000');
    killStalePort5000();
    startPython();
  }, 250);
});

app.on('window-all-closed', (e) => {
  if (!app.isQuitting) {
    e.preventDefault();
  }
});

app.on('before-quit', () => {
  app.isQuitting = true;
  globalShortcut.unregister(BOSS_KEY);
});

