'use strict';

const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain, shell, dialog } = require('electron');
const { spawn } = require('child_process');
const treeKill = require('tree-kill');
const path = require('path');
const http = require('http');
const fs = require('fs');

// ── Config ──────────────────────────────────────────────────────────────────
const ROOT       = path.resolve(__dirname, '..');          // project root
const SERVER_URL = 'http://127.0.0.1:5000';
const GUI_SCRIPT = path.join(ROOT, 'gui.py');
const ICON_PATH  = path.join(__dirname, 'icon.ico');
const ICON_PNG   = path.join(__dirname, 'icon.png');
const LOAD_HTML  = path.join(__dirname, 'renderer', 'loading.html');

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

// Find Python executable (.venv preferred, then system)
function findPython() {
  const candidates = [
    path.join(ROOT, '.venv', 'Scripts', 'python.exe'),
    path.join(ROOT, '.python310', 'python.exe'),
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

// ── State ────────────────────────────────────────────────────────────────────
let mainWindow  = null;
let tray        = null;
let pyProc      = null;
let pyPid       = null;
let serverReady = false;

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

// ── Python process ───────────────────────────────────────────────────────────
function startPython() {
  const pythonPath = findPython();
  console.log('[main] Starting Python:', pythonPath, GUI_SCRIPT);

  pyProc = spawn(
    pythonPath,
    ['-X', 'utf8', '-u', GUI_SCRIPT, '--electron'],
    {
      cwd: ROOT,
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

  // Read raw bytes as Buffer → decode UTF-8 manually to avoid Windows GBK mangling
  pyProc.stdout.on('data', createLineReader(line => {
    console.log('[python]', line);
    sendToRenderer('log', line);
  }));

  pyProc.stderr.on('data', createLineReader(line => {
    console.log('[python:err]', line);
    sendToRenderer('log', line);
    if (line.includes('Application startup complete') || line.includes('Uvicorn running on')) {
      if (!serverReady) {
        serverReady = true;
        pollServer();
      }
    }
  }));

  pyProc.on('error', err => {
    console.error('[python:error]', err);
    sendToRenderer('log', String(err));
  });

  pyProc.on('spawn', () => {
    pyPid = pyProc.pid;
    console.log('[main] Python PID:', pyPid);
    sendToRenderer('status', 'starting');
    setTimeout(() => { if (!serverReady) pollServer(); }, 20000);
  });

  pyProc.on('exit', (code) => {
    console.log('[python] exited with code', code);
    if (!app.isQuitting) {
      sendToRenderer('log', `[Python 进程退出: code=${code}]`);
    }
  });
}

// Poll until server responds with valid content, then load the app
function pollServer(retries = 0) {
  if (retries > 90) {
    sendToRenderer('log', '[错误] 服务器启动超时，请检查 Python 环境');
    return;
  }
  const req = http.get(SERVER_URL, (res) => {
    let body = '';
    res.on('data', d => { body += d; });
    res.on('end', () => {
      if (res.statusCode === 200 && body.includes('AutoScriptor')) {
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
    title: 'AutoScriptor',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  // Show once DOM is ready
  mainWindow.once('ready-to-show', () => mainWindow.show());

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

  tray.setToolTip('AutoScriptor');
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
function quitApp() {
  app.isQuitting = true;
  if (pyPid) {
    try { treeKill(pyPid, 'SIGTERM'); } catch (_) {}
  }
  if (pyProc) {
    try { pyProc.kill(); } catch (_) {}
  }
  setTimeout(() => {
    tray?.destroy();
    app.quit();
  }, 800);
}

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(() => {
  app.isQuitting = false;
  createMainWindow();
  createTray();
  startPython();
});

app.on('window-all-closed', (e) => {
  // Only keep running in tray when not explicitly quitting
  if (!app.isQuitting) {
    e.preventDefault();
  }
});

app.on('before-quit', () => {
  app.isQuitting = true;
  if (pyPid) {
    try { treeKill(pyPid, 'SIGTERM'); } catch (_) {}
  }
});
