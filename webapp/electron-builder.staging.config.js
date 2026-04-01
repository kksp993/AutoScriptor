/**
 * 发行打包：先在 webapp 执行 npm run prepare-release-shell，再于 webapp 目录下
 * npx electron-builder --config electron-builder.staging.config.js（cwd = webapp）。
 *
 * 默认：portable 单文件 exe（backend.zip、data 均打入包内），用户只分发一个安装包；
 * 首次运行即打开与开发环境一致的 installer.html 向导（解压引擎 → MuMu/ADB 路径校验）。
 *
 * 可选：
 * - NSIS：AUTOSCRIPTOR_ELECTRON_NSIS=1 或 build_release.py --electron-nsis（系统级安装向导，非 HTML）
 * - 文件夹 ZIP：AUTOSCRIPTOR_ELECTRON_ZIP=1 或 --electron-zip（解压目录后运行，调试用）
 *
 * NSIS 安装慢：可设 AUTOSCRIPTOR_NSIS_FAST_INSTALL=1 → nsis.compression=store
 */
const fs = require('fs');
const path = require('path');

const projectRoot = path.join(__dirname, '..');
const useNsis = process.env.AUTOSCRIPTOR_ELECTRON_NSIS === '1';
const useZip = process.env.AUTOSCRIPTOR_ELECTRON_ZIP === '1';
/** store：安装时几乎不再解压算法开销，大体积包时进度条更顺滑；安装包比 normal 更大 */
const nsisCompression =
  process.env.AUTOSCRIPTOR_NSIS_FAST_INSTALL === '1' ? 'store' : 'normal';

function pickWinIcon() {
  const br = path.join(__dirname, 'buildResources', 'icon.ico');
  const rootIco = path.join(__dirname, 'icon.ico');
  const rootPng = path.join(__dirname, 'icon.png');
  if (fs.existsSync(br)) return br;
  if (fs.existsSync(rootIco)) return rootIco;
  if (fs.existsSync(rootPng)) return rootPng;
  return br;
}

const winIcon = pickWinIcon();

let winTarget;
if (useNsis) {
  winTarget = [{ target: 'nsis', arch: ['x64'] }];
} else if (useZip) {
  winTarget = [{ target: 'zip', arch: ['x64'] }];
} else {
  winTarget = [{ target: 'portable', arch: ['x64'] }];
}

const cfg = {
  appId: 'com.autoscriptor.app',
  productName: '造笔',
  copyright: '造笔 AutoScriptor',

  directories: {
    app: '.release-staging',
    output: path.join(projectRoot, 'dist_electron'),
    buildResources: path.join(__dirname, 'buildResources'),
  },

  files: [
    '**/*',
    '!**/*.map',
    '!**/README.md',
    '!**/readme.md',
  ],

  extraFiles: [
    {
      from: path.join(projectRoot, 'dist', 'data'),
      to: 'data',
      filter: ['**/*'],
    },
    {
      from: path.join(projectRoot, 'dist', 'license'),
      to: 'license',
      filter: ['**/*'],
    },
    // 与 造笔.exe 同级（application root）。portable 单文件解压后，extraResources 进 resources/
    // 在部分环境下与 process.resourcesPath 不一致，导致找不到 zip；extraFiles 更稳。
    {
      from: path.join(projectRoot, 'dist', 'backend.zip'),
      to: 'backend.zip',
    },
  ],

  win: {
    target: winTarget,
    icon: winIcon,
    signAndEditExecutable: false,
    ...(useZip && !useNsis
      ? {
          artifactName: 'AutoScriptor_Zao_${version}.${ext}',
        }
      : {}),
  },
};

if (!useNsis && !useZip) {
  cfg.portable = {
    artifactName: 'AutoScriptor_Zao_Install.exe',
  };
}

if (useNsis) {
  cfg.nsis = {
    oneClick: false,
    allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    shortcutName: '造笔',
    installerIcon: winIcon,
    uninstallerIcon: winIcon,
    artifactName: 'AutoScriptor_Zao_installer.exe',
    compression: nsisCompression,
  };
}

module.exports = cfg;
