'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electron', {
  // Loading page APIs
  onLog:       (cb) => ipcRenderer.on('log',    (_e, msg)    => cb(msg)),
  onStatus:    (cb) => ipcRenderer.on('status', (_e, status) => cb(status)),

  // Window controls
  windowTray:     () => ipcRenderer.send('window-tray'),
  windowMinimize: () => ipcRenderer.send('window-minimize'),
  windowClose:    () => ipcRenderer.send('window-close'),
});
