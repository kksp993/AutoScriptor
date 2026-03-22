'use strict';

const { contextBridge, ipcRenderer } = require('electron');

// Expose only what the renderer pages need
contextBridge.exposeInMainWorld('electron', {
  onLog:       (cb) => ipcRenderer.on('log',    (_e, msg)    => cb(msg)),
  onStatus:    (cb) => ipcRenderer.on('status', (_e, status) => cb(status)),
  windowTray:  () => ipcRenderer.send('window-tray'),
  windowClose: () => ipcRenderer.send('window-close'),
});
