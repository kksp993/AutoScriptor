'use strict';

const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain, shell, dialog } = require('electron');
const { spawn } = require('child_process');
const treeKill = require('tree-kill');
const path = require('path');
const http = require('http');
const fs = require('fs');

// ── Config ──────────────────────────────────────────────────────────────────
/** 开发模式：仓库根目录。发行安装包：install.json 中的 installRoot，或 exe 同层（旧版整包）。 */
const SERVER_URL = 'http://127.0.0.1:5000';

let _rootCache = null;
function invalidateRootCache() {
  _rootCache = null;
}

function getRoot() {
  if (!app.isPackaged) {
    return path.resolve(__dirname, '..');
  }
  if (_rootCache !== null) return _rootCache;
  try {
    const marker = path.join(app.getPath('userData'), 'install.json');
    if (fs.existsSync(marker)) {
      const j = JSON.parse(fs.readFileSync(marker, 'utf8'));
      if (j.installRoot && typeof j.installRoot === 'string') {
        const r = path.resolve(j.installRoot);
        if (fs.existsSync(r)) {
          _rootCache = r;
          return _rootCache;
        }
      }
    }
  } catch (_) {}
  _rootCache = path.dirname(process.execPath);
  return _rootCache;
}

function guiScriptPath() {
  return path.join(getRoot(), 'gui.py');
}

function installStepScriptPath() {
  return path.join(getRoot(), 'services', 'installer', 'install_steps.py');
}

function getBackendEngineExe() {
  const name = process.platform === 'win32' ? 'autoscriptor-engine.exe' : 'autoscriptor-engine';
  return path.join(getRoot(), 'backend', name);
}

/** 发行包内 backend.zip：优先 exe 同级（extraFiles），其次 resources（旧布局）。portable 解压后前者更可靠。 */
function getBackendZipPath() {
  if (!app.isPackaged) {
    return path.join(process.resourcesPath, 'backend.zip');
  }
  const besideExe = path.join(path.dirname(process.execPath), 'backend.zip');
  if (fs.existsSync(besideExe)) return besideExe;
  const inResources = path.join(process.resourcesPath, 'backend.zip');
  if (fs.existsSync(inResources)) return inResources;
  return inResources;
}

const ICON_PATH = path.join(__dirname, 'icon.ico');
const ICON_PNG = path.join(__dirname, 'icon.png');
const LOAD_HTML = path.join(__dirname, 'renderer', 'loading.html');
const INSTALL_HTML = path.join(__dirname, 'renderer', 'installer.html');

/** 窗口 / 托盘用图标：优先 .ico，其次同目录 icon.png（避免缺失时托盘为空白） */
function loadAppIcon() {
  if (fs.existsSync(ICON_PATH)) return nativeImage.createFromPath(ICON_PATH);
  if (fs.existsSync(ICON_PNG)) return nativeImage.createFromPath(ICON_PNG);
  return undefined;
}

/** 托盘区 16×16（Windows 任务栏通知区域） */
function loadTrayIcon() {
  const base = loadAppIcon();
  if (!base || base.isEmpty()) return undefined;
  try {
    return base.resize({ width: 16, height: 16 });
  } catch (_) {
    return base;
  }
}

/**
 * 主窗口与安装向导共用。Vue 3 在 WebUI 的 index.html 内联模板依赖运行时编译器（内部会 new Function）。
 * Electron 在 nodeIntegration:false + preload 时默认 sandbox:true，沙箱内对 eval/newFunction 的限制会导致
 * 页面一直停留在未编译的 `{{ }}`；关闭 sandbox 后由 meta CSP + 无 node 集成仍保持隔离。
 */
function browserWindowWebPreferences() {
  return {
    preload: path.join(__dirname, 'preload.js'),
    nodeIntegration: false,
    contextIsolation: true,
    sandbox: false,
  };
}

// Find Python executable (.venv preferred, then system)
function findPython() {
  const candidates = [
    path.join(getRoot(), '.venv', 'Scripts', 'python.exe'),
    path.join(getRoot(), '.python310', 'python.exe'),
    'python',
  ];
  for (const p of candidates) {
    try {
      if (p === 'python' || fs.existsSync(p)) return p;
    } catch (_) {}
  }
  return 'python';
}

/**
 * 解码管道一行：优先 UTF-8；Windows 上若像「UTF-8 误读 GBK」则回退 gb18030。
 * （与 gui.py 强制 UTF-8 stdio 互补，防止仍有库绕过 TextIO 写 cp936）
 */
function decodePipeLine(buf) {
  const utf8 = buf.toString('utf-8');
  if (process.platform !== 'win32' || buf.length === 0) return utf8;
  if (utf8.includes('\uFFFD')) {
    try {
      const g = buf.toString('gb18030');
      if (!g.includes('\uFFFD')) return g;
    } catch (_) { /* ignore */ }
  }
  // 常见：管道实为 GBK，被当成 UTF-8 解成「璐﹀彿…」类字形
  const mojibakeHint =
    /[瀵嗙爜鐧诲綍鎵嬫満鍙风櫥褰璐﹀彿鍚屾剰杩涘叆娓告垯]/.test(utf8);
  if (mojibakeHint) {
    try {
      const g = buf.toString('gb18030');
      if (g.includes('\uFFFD')) return utf8;
      const han = (s) => (s.match(/[\u4e00-\u9fff]/g) || []).length;
      if (han(g) >= han(utf8) - 2) return g;
    } catch (_) { /* ignore */ }
  }
  return utf8;
}

/**
 * Split a raw Buffer stream into lines, decode each line for Electron pipe.
 */
function createLineReader(onLine) {
  let buf = Buffer.alloc(0);
  return (chunk) => {
    buf = Buffer.concat([buf, chunk]);
    let start = 0;
    for (let i = 0; i < buf.length; i++) {
      // LF = 0x0A; also handle CR+LF
      if (buf[i] === 0x0A) {
        let end = i;
        if (end > start && buf[end - 1] === 0x0D) end--;
        onLine(decodePipeLine(buf.slice(start, end)));
        start = i + 1;
      }
    }
    buf = buf.slice(start);
  };
}

/** 开发：venv 就绪。发行包：backend 下已有 Nuitka 引擎。 */
function isInstalled() {
  if (app.isPackaged) {
    return fs.existsSync(getBackendEngineExe());
  }
  return fs.existsSync(path.join(getRoot(), '.venv', 'Scripts', 'python.exe'));
}

/** 安装向导专用：命令行带 `--installer` / `--install-wizard` 时始终只打开向导，不启动主窗口与 Python。 */
function isInstallerWizardArgv() {
  return process.argv.some((a) => a === '--installer' || a === '--install-wizard');
}

/** userData/install.json：与 installer:get-existing-install-info 一致。 */
function readInstallJsonExisting() {
  try {
    const marker = path.join(app.getPath('userData'), 'install.json');
    if (!fs.existsSync(marker)) {
      return { hasExisting: false, installRoot: null, version: null };
    }
    const j = JSON.parse(fs.readFileSync(marker, 'utf8'));
    const ir = j.installRoot && typeof j.installRoot === 'string' ? path.resolve(j.installRoot) : null;
    if (!ir || !fs.existsSync(ir)) {
      return { hasExisting: false, installRoot: null, version: j.version || null };
    }
    return { hasExisting: true, installRoot: ir, version: j.version || null };
  } catch (_) {
    return { hasExisting: false, installRoot: null, version: null };
  }
}

// ── State ────────────────────────────────────────────────────────────────────
let mainWindow    = null;
let tray          = null;
let pyProc        = null;
let pyPid         = null;
let serverReady   = false;
let installerProc = null;
let installerMode = false;
/** 防止重复执行退出逻辑（treeKill 异步完成前勿二次 kill） */
let quitStarted = false;

/** 加载页尚未完成时 Python 已输出日志，IPC 无订阅会丢包 —— 先缓冲再补发 */
const LOG_BUFFER_MAX = 500;
const logBuffer = [];
let loadingScreenLogFlushDone = false;
let pendingStatus = null;

// ── Single instance lock ─────────────────────────────────────────────────────
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      if (!mainWindow.isVisible()) mainWindow.show();
      mainWindow.focus();
    }
  });
}

// ── Port cleanup ─────────────────────────────────────────────────────────────
/**
 * Kill any stale process listening on port 5000 from a previous run.
 * Synchronous — safe to call before startPython().
 */
function killStalePort5000() {
  if (process.platform !== 'win32') return;
  const { execSync } = require('child_process');
  try {
    const output = execSync('netstat -ano', { encoding: 'utf-8', timeout: 5000 });
    const pids = new Set();
    for (const line of output.split('\n')) {
      if (line.includes(':5000') && line.includes('LISTENING')) {
        const parts = line.trim().split(/\s+/);
        const pid = parseInt(parts[parts.length - 1], 10);
        if (pid > 0 && pid !== process.pid) pids.add(pid);
      }
    }
    for (const pid of pids) {
      console.log(`[main] Killing stale process on port 5000 (PID: ${pid})`);
      try { execSync(`taskkill /PID ${pid} /T /F`, { timeout: 5000 }); } catch (_) {}
    }
  } catch (_) {}
}

// ── Backend process (Python dev or Nuitka engine in packaged app) ───────────
function maybeNotifyServerReady(line) {
  if (line.includes('Application startup complete') || line.includes('Uvicorn running on')) {
    if (!serverReady) {
      serverReady = true;
      pollServer();
    }
  }
}

function attachBackendProcessHandlers() {
  pyProc.stdout.on('data', createLineReader(line => {
    console.log('[backend]', line);
    sendToRenderer('log', line);
    maybeNotifyServerReady(line);
  }));

  pyProc.stderr.on('data', createLineReader(line => {
    console.log('[backend:err]', line);
    sendToRenderer('log', line);
    maybeNotifyServerReady(line);
  }));

  pyProc.on('error', err => {
    console.error('[backend:error]', err);
    sendToRenderer('log', String(err));
  });

  pyProc.on('spawn', () => {
    pyPid = pyProc.pid;
    console.log('[main] Backend PID:', pyPid);
    sendToRenderer('status', 'starting');
    setTimeout(() => { if (!serverReady) pollServer(); }, 20000);
  });

  pyProc.on('exit', (code) => {
    console.log('[backend] exited with code', code);
    if (!app.isQuitting) {
      sendToRenderer('log', `[后端进程退出: code=${code}]`);
    }
  });
}

function startPython() {
  const engineExe = getBackendEngineExe();
  if (app.isPackaged && fs.existsSync(engineExe)) {
    const backendCwd = path.dirname(engineExe);
    console.log('[main] Starting packaged engine:', engineExe, 'cwd:', backendCwd);
    pyProc = spawn(engineExe, ['--electron'], {
      cwd: backendCwd,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        AUTOSCRIPTOR_ELECTRON_PIPE: '1',
        AUTOSCRIPTOR_ELECTRON: '1',
        UVICORN_LOG_LEVEL: 'info',
        NO_COLOR: '1',
      },
    });
    attachBackendProcessHandlers();
    return;
  }

  const pythonPath = findPython();
  const guiScript = guiScriptPath();
  console.log('[main] Starting Python:', pythonPath, guiScript);

  pyProc = spawn(
    pythonPath,
    ['-X', 'utf8', '-u', guiScript, '--electron'],
    {
      cwd: getRoot(),
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        PYTHONIOENCODING: 'utf-8',
        PYTHONUTF8: '1',
        AUTOSCRIPTOR_ELECTRON_PIPE: '1',
        NO_COLOR: '1',
      },
    },
  );

  attachBackendProcessHandlers();
}

// Poll until server responds with valid content, then load the app
function pollServer(retries = 0) {
  if (retries > 90) {
    sendToRenderer('log', '[错误] 服务器启动超时，请检查本机环境与后端日志');
    return;
  }
  const req = http.get(SERVER_URL, (res) => {
    let body = '';
    res.on('data', d => { body += d; });
    res.on('end', () => {
      if (res.statusCode === 200 && (body.includes('AutoScriptor') || body.includes('造笔'))) {
        console.log('[main] Server ready, loading app...');
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
  req.setTimeout(2000, () => { req.destroy(); setTimeout(() => pollServer(retries + 1), 1000); });
}

// ── Window ───────────────────────────────────────────────────────────────────
function createMainWindow() {
  const icon = loadAppIcon();

  mainWindow = new BrowserWindow({
    width:  1400,
    height: 900,
    minWidth:  900,
    minHeight: 600,
    show: false,
    icon,
    title: '造笔 - AutoScriptor',
    webPreferences: browserWindowWebPreferences(),
  });

  // Show once DOM is ready
  mainWindow.once('ready-to-show', () => mainWindow.show());

  // 转发 renderer console 到主进程 stdout（便于终端看到前端 JS 报错）
  mainWindow.webContents.on('console-message', (_e, level, msg, line, src) => {
    const tag = ['V','I','W','E'][level] || 'L';
    console.log(`[renderer:${tag}] ${msg}  (${src}:${line})`);
  });

  // Load loading screen first；等页面真正加载完再允许发 log（否则早到的行会丢）
  loadingScreenLogFlushDone = false;
  // 首次导航必是 loading.html；Python 日志可能更早产生，须在订阅就绪后补发缓冲
  mainWindow.webContents.once('did-finish-load', () => {
    flushLoadingScreenIpc();
  });
  mainWindow.loadFile(LOAD_HTML);

  // Open external links in browser, not in Electron
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  // Close button quits the app
  mainWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      quitApp();
    }
  });

  return mainWindow;
}

// ── Tray ─────────────────────────────────────────────────────────────────────
function createTray() {
  const icon = loadTrayIcon() || nativeImage.createEmpty();

  tray = new Tray(icon);

  const menu = Menu.buildFromTemplate([
    { label: '显示窗口',    click: () => { mainWindow?.show(); mainWindow?.focus(); } },
    { label: '隐藏窗口',    click: () => mainWindow?.hide() },
    { type: 'separator' },
    { label: '在浏览器中打开', click: () => shell.openExternal(SERVER_URL) },
    { type: 'separator' },
    { label: '退出',        click: () => quitApp() },
  ]);

  tray.setToolTip('造笔 - AutoScriptor');
  tray.setContextMenu(menu);
  tray.on('click', () => {
    if (mainWindow?.isVisible()) {
      mainWindow.isMinimized() ? mainWindow.show() : mainWindow.hide();
    } else {
      mainWindow?.show();
    }
  });
  tray.on('right-click', () => tray.popUpContextMenu(menu));
}

// ── Installer Window ──────────────────────────────────────────────────────────
function createInstallerWindow() {
  const icon = loadAppIcon();
  installerMode = true;

  mainWindow = new BrowserWindow({
    width: 960,
    height: 640,
    frame: false,
    resizable: false,
    show: false,
    icon,
    title: '造笔 安装向导',
    webPreferences: browserWindowWebPreferences(),
  });

  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.loadFile(INSTALL_HTML);

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

/** Transition from installer to normal app mode */
function transitionToApp() {
  installerMode = false;
  invalidateRootCache();

  if (mainWindow && !mainWindow.isDestroyed()) {
    app.isQuitting = true;
    mainWindow.close();
    app.isQuitting = false;
    mainWindow = null;
  }

  killStalePort5000();
  createMainWindow();
  createTray();
  startPython();
}

// ── Installer IPC handlers ──────────────────────────────────────────────────
ipcMain.handle('installer:get-project-root', () => getRoot());

ipcMain.handle('installer:get-mode', () => {
  invalidateRootCache();
  if (!app.isPackaged) {
    return { mode: 'development' };
  }
  const zipPath = getBackendZipPath();
  const hasZip = fs.existsSync(zipPath);
  const engineOk = fs.existsSync(getBackendEngineExe());
  return {
    mode: 'packaged',
    hasBackendZip: hasZip,
    installed: engineOk,
  };
});

ipcMain.handle('installer:default-install-dir', () => {
  return path.join(app.getPath('documents'), 'AutoScriptor');
});

/** 读取 userData/install.json，用于覆盖安装提示 */
ipcMain.handle('installer:get-existing-install-info', () => readInstallJsonExisting());

ipcMain.handle('installer:get-wizard-context', () => {
  invalidateRootCache();
  const isWizard = isInstallerWizardArgv();
  let appVersion = '0.0.0';
  try {
    appVersion = require('./package.json').version;
  } catch (_) {}
  const packaged = app.isPackaged;
  const engineOk = packaged && fs.existsSync(getBackendEngineExe());
  const existing = readInstallJsonExisting();
  let uninstallBatPath = null;
  if (existing.installRoot) {
    const bat = path.join(existing.installRoot, '卸载造笔.bat');
    if (fs.existsSync(bat)) uninstallBatPath = bat;
  }
  const needsUninstallGate = isWizard && packaged && engineOk;
  return {
    isWizard,
    packaged,
    appVersion,
    engineOk,
    hasExistingInstall: existing.hasExisting,
    installRoot: existing.installRoot,
    recordVersion: existing.version,
    uninstallBatPath,
    needsUninstallGate,
  };
});

ipcMain.handle('installer:run-uninstall-bat', () => {
  const ex = readInstallJsonExisting();
  if (!ex.installRoot || !fs.existsSync(ex.installRoot)) {
    throw new Error('未找到安装目录，请先点击「刷新状态」');
  }
  const bat = path.join(ex.installRoot, '卸载造笔.bat');
  if (!fs.existsSync(bat)) {
    throw new Error('未找到卸载脚本：' + bat);
  }
  const child = spawn('cmd.exe', ['/c', 'start', '""', bat], {
    cwd: ex.installRoot,
    detached: true,
    stdio: 'ignore',
  });
  child.unref();
  return { ok: true, path: bat };
});

ipcMain.handle('installer:open-install-root', (_event, maybeRoot) => {
  const s = maybeRoot != null ? String(maybeRoot).trim() : '';
  const r = s ? path.resolve(s) : null;
  const target = r && fs.existsSync(r) ? r : readInstallJsonExisting().installRoot;
  if (!target || !fs.existsSync(target)) {
    return { ok: false, error: '目录不存在' };
  }
  shell.openPath(target);
  return { ok: true };
});

/**
 * 安装前：释放本机 5000 端口，并结束「可执行文件路径位于指定 backend 目录下」的进程（缓解 EPERM）。
 * opts: { installRoot, previousInstallRoot? }
 */
function releaseInstallLocks(opts) {
  const o = opts && typeof opts === 'object' ? opts : {};
  const roots = new Set();
  const addBackend = (r) => {
    const s = String(r || '').trim();
    if (s.length < 4) return;
    const abs = path.resolve(s);
    roots.add(path.join(abs, 'backend'));
  };
  addBackend(o.installRoot);
  if (o.previousInstallRoot) addBackend(o.previousInstallRoot);

  killStalePort5000();

  if (process.platform !== 'win32' || roots.size === 0) {
    return { ok: true, killedNote: 'port5000' };
  }

  const dirList = [...roots].map((d) => d.replace(/'/g, "''"));
  const ps = `
$dirs = @(${dirList.map((d) => `'${d}'`).join(',')})
Get-CimInstance Win32_Process | ForEach-Object {
  $exe = $_.ExecutablePath
  if (-not $exe) { return }
  foreach ($d in $dirs) {
    if ($exe.StartsWith($d, [System.StringComparison]::OrdinalIgnoreCase)) {
      Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
      break
    }
  }
}
`;
  try {
    const { execFileSync } = require('child_process');
    execFileSync(
      'powershell.exe',
      ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps],
      { encoding: 'utf8', windowsHide: true, timeout: 60000 },
    );
  } catch (e) {
    console.warn('[releaseInstallLocks]', e && e.message ? e.message : e);
  }
  return { ok: true, killedNote: 'port5000+backend' };
}

ipcMain.handle('installer:release-install-locks', async (_event, opts) => releaseInstallLocks(opts));

ipcMain.handle('installer:run-packaged', async (_event, opts) => {
  const installRoot = path.resolve(String(opts && opts.installRoot ? opts.installRoot : '').trim());
  if (installRoot.length < 4) {
    throw new Error('请选择有效的安装目录');
  }
  let previousInstallRoot = null;
  try {
    const marker = path.join(app.getPath('userData'), 'install.json');
    if (fs.existsSync(marker)) {
      const j = JSON.parse(fs.readFileSync(marker, 'utf8'));
      if (j.installRoot && typeof j.installRoot === 'string') {
        previousInstallRoot = path.resolve(j.installRoot);
      }
    }
  } catch (_) {}
  releaseInstallLocks({ installRoot, previousInstallRoot });
  if (process.platform === 'win32') {
    const low = installRoot.toLowerCase();
    if (/^[a-z]:\\windows$/i.test(low) || low.includes(':\\windows\\system32')) {
      throw new Error('请勿安装到 Windows 系统目录，请选择其他盘符或用户目录下的文件夹');
    }
  }
  const { runPackagedInstall } = require('./install-packaged.cjs');
  const pkg = require('./package.json');
  const send = (data) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('installer:progress', data);
    }
  };
  await runPackagedInstall({
    installRoot,
    resourcesPath: process.resourcesPath,
    zipPath: getBackendZipPath(),
    exeDir: path.dirname(process.execPath),
    appVersion: pkg.version,
    userDataPath: app.getPath('userData'),
    send,
  });
  invalidateRootCache();
});
ipcMain.on('installer:start', (event, config) => {
  const pythonPath = findPython();
  const args = [installStepScriptPath(), '--project-root', getRoot()];
  if (config && config.pipSource) {
    args.push('--pip-source', config.pipSource);
  }
  if (config && config.fresh) {
    args.push('--fresh');
  }

  console.log('[installer] Starting:', pythonPath, args.join(' '));

  installerProc = spawn(pythonPath, args, {
    cwd: getRoot(),
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
      ...process.env,
      PYTHONIOENCODING: 'utf-8',
      PYTHONUTF8: '1',
      NO_COLOR: '1',
    },
  });

  const sendProgress = (data) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('installer:progress', data);
    }
  };

  // Installer 脚本输出 ensure_ascii=True 的 JSON，纯 ASCII 安全，
  // 但 pip 子进程的日志可能含中文；统一用 UTF-8 解码，不走 GBK 回退
  const utf8Line = (onLine) => {
    let remainder = Buffer.alloc(0);
    return (chunk) => {
      remainder = Buffer.concat([remainder, chunk]);
      let start = 0;
      for (let i = 0; i < remainder.length; i++) {
        if (remainder[i] === 0x0A) {
          let end = i;
          if (end > start && remainder[end - 1] === 0x0D) end--;
          onLine(remainder.slice(start, end).toString('utf-8'));
          start = i + 1;
        }
      }
      remainder = remainder.slice(start);
    };
  };

  installerProc.stdout.on('data', utf8Line(line => {
    console.log('[installer:out]', line);
    try {
      sendProgress(JSON.parse(line));
    } catch {
      sendProgress({ type: 'log', message: line });
    }
  }));

  installerProc.stderr.on('data', utf8Line(line => {
    console.log('[installer:err]', line);
    sendProgress({ type: 'log', message: line });
  }));

  installerProc.on('error', err => {
    console.error('[installer:error]', err);
    sendProgress({ type: 'error', message: String(err) });
  });

  installerProc.on('exit', (code) => {
    console.log('[installer] exited with code', code);
    installerProc = null;
  });
});

ipcMain.on('installer:launch', () => {
  if (installerProc) {
    try { installerProc.kill(); } catch (_) {}
    installerProc = null;
  }
  transitionToApp();
});

// ── Installer path-verification IPC ─────────────────────────────────────────
ipcMain.handle('installer:read-config-paths', () => {
  const cfgPath = path.join(getRoot(), 'config.json');
  try {
    const data = JSON.parse(fs.readFileSync(cfgPath, 'utf-8'));
    return data.emulator || {};
  } catch {
    return {};
  }
});

ipcMain.handle('installer:browse-path', async (_event, opts) => {
  if (!mainWindow) return null;
  const props = opts && opts.isDirectory ? ['openDirectory'] : ['openFile'];
  const filters = (!opts?.isDirectory && opts?.filters) ? opts.filters : undefined;
  const result = await dialog.showOpenDialog(mainWindow, {
    title: (opts && opts.title) || '选择路径',
    properties: props,
    filters: filters,
  });
  if (result.canceled || !result.filePaths.length) return null;
  return result.filePaths[0];
});

ipcMain.handle('installer:validate-path', (_event, p) => {
  try { return fs.existsSync(p); } catch { return false; }
});

ipcMain.handle('installer:save-paths', (_event, paths) => {
  const cfgPath = path.join(getRoot(), 'config.json');
  try {
    const data = JSON.parse(fs.readFileSync(cfgPath, 'utf-8'));
    if (!data.emulator) data.emulator = {};
    for (const [k, v] of Object.entries(paths)) {
      data.emulator[k] = v;
    }
    fs.writeFileSync(cfgPath, JSON.stringify(data, null, 2), 'utf-8');
    return true;
  } catch {
    return false;
  }
});

// ── IPC handlers (window controls from renderer) ──────────────────────────────
ipcMain.on('window-tray', () => {
  mainWindow?.hide();
});

ipcMain.on('window-minimize', () => {
  mainWindow?.minimize();
});

ipcMain.on('window-close', () => {
  quitApp();
});

// ── IPC ───────────────────────────────────────────────────────────────────────
function sendToRenderer(channel, data) {
  if (!mainWindow || mainWindow.isDestroyed()) return;

  if (channel === 'log') {
    const line = String(data);
    logBuffer.push(line);
    if (logBuffer.length > LOG_BUFFER_MAX) logBuffer.shift();
    if (loadingScreenLogFlushDone) {
      mainWindow.webContents.send('log', line);
    }
    return;
  }

  if (channel === 'status') {
    pendingStatus = data;
    if (loadingScreenLogFlushDone) {
      mainWindow.webContents.send('status', data);
    }
    return;
  }

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

// ── Quit ─────────────────────────────────────────────────────────────────────
function finishQuit() {
  pyPid = null;
  pyProc = null;
  killStalePort5000();
  setTimeout(() => {
    tray?.destroy();
    app.quit();
  }, 300);
}

function quitApp() {
  if (quitStarted) return;
  quitStarted = true;
  app.isQuitting = true;

  if (installerProc) {
    try { installerProc.kill(); } catch (_) {}
    installerProc = null;
  }

  // Windows：必须先等 taskkill /T /F 整树结束，再退出 Electron。
  // 若紧跟 pyProc.kill()，只会杀掉 gui.py 父进程，multiprocessing 子进程（uvicorn）易残留占端口。
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

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(() => {
  app.isQuitting = false;

  if (isInstallerWizardArgv()) {
    createInstallerWindow();
    return;
  }

  if (isInstalled()) {
    killStalePort5000();
    createMainWindow();
    createTray();
    startPython();
  } else {
    createInstallerWindow();
  }
});

app.on('window-all-closed', (e) => {
  // Only keep running in tray when not explicitly quitting
  if (!app.isQuitting) {
    e.preventDefault();
  }
});

app.on('before-quit', () => {
  app.isQuitting = true;
});
