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

  // Installer APIs
  installer: {
    getProjectRoot: () => ipcRenderer.invoke('installer:get-project-root'),
    getInstallerMode: () => ipcRenderer.invoke('installer:get-mode'),
    defaultInstallDir: () => ipcRenderer.invoke('installer:default-install-dir'),
    runPackagedInstall: (opts) => ipcRenderer.invoke('installer:run-packaged', opts),
    startInstall:   (config) => ipcRenderer.send('installer:start', config),
    onProgress:     (cb) => ipcRenderer.on('installer:progress', (_e, data) => cb(data)),
    launch:         () => ipcRenderer.send('installer:launch'),
    readConfigPaths: () => ipcRenderer.invoke('installer:read-config-paths'),
    browsePath:      (opts) => ipcRenderer.invoke('installer:browse-path', opts),
    validatePath:    (p) => ipcRenderer.invoke('installer:validate-path', p),
    savePaths:       (paths) => ipcRenderer.invoke('installer:save-paths', paths),
  },
});
