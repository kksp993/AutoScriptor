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
    getExistingInstallInfo: () => ipcRenderer.invoke('installer:get-existing-install-info'),
    getWizardContext: () => ipcRenderer.invoke('installer:get-wizard-context'),
    runUninstallBat: () => ipcRenderer.invoke('installer:run-uninstall-bat'),
    openInstallRoot: (root) => ipcRenderer.invoke('installer:open-install-root', root),
    releaseInstallLocks: (opts) => ipcRenderer.invoke('installer:release-install-locks', opts),
    dryRunPackagedInstall: (opts) => ipcRenderer.invoke('installer:dry-run-packaged', opts),
    dryRunBackendIncremental: (opts) => ipcRenderer.invoke('installer:dry-run-backend-incremental', opts),
    runPackagedInstall: (opts) => ipcRenderer.invoke('installer:run-packaged', opts),
    applyBackendIncremental: (opts) => ipcRenderer.invoke('installer:apply-backend-incremental', opts),
    startInstall:   (config) => ipcRenderer.send('installer:start', config),
    onProgress:     (cb) => ipcRenderer.on('installer:progress', (_e, data) => cb(data)),
    launch:         () => ipcRenderer.send('installer:launch'),
    readConfigPaths: () => ipcRenderer.invoke('installer:read-config-paths'),
    browsePath:      (opts) => ipcRenderer.invoke('installer:browse-path', opts),
    validatePath:    (p, opts) => ipcRenderer.invoke('installer:validate-path', p, opts || {}),
    validateSetup:   () => ipcRenderer.invoke('installer:validate-setup'),
    validateInstallDir: (p, opts) => ipcRenderer.invoke('installer:validate-install-dir', p, opts || {}),
    savePaths:       (paths) => ipcRenderer.invoke('installer:save-paths', paths),
  },

  releaseUpdate: {
    choosePackage: () => ipcRenderer.invoke('release-update:choose-package'),
    dryRunPackage: (opts) => ipcRenderer.invoke('release-update:dry-run', opts || {}),
    applyPackage: (opts) => ipcRenderer.invoke('release-update:apply', opts || {}),
    onProgress: (cb) => ipcRenderer.on('release-update:progress', (_e, data) => cb(data)),
  },
});
