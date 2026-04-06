const nsisCompression =
  process.env.AUTOSCRIPTOR_NSIS_FAST_INSTALL === '1' ? 'store' : 'normal';

/**
 * AutoScriptor 发行版 Electron Builder 配置（与 electron-builder.staging.config.js 策略一致）
 *
 * 默认：portable 单文件 AutoScriptor_Zao_Install_${version}.exe（首次运行 = HTML 安装向导；安装目录写入 造笔.exe 启动器）。
 * NSIS：AUTOSCRIPTOR_ELECTRON_NSIS=1
 * ZIP：AUTOSCRIPTOR_ELECTRON_ZIP=1
 *
 * 输出目录 ../dist_electron 与 ../dist 分离。
 */

const useNsis = process.env.AUTOSCRIPTOR_ELECTRON_NSIS === '1';
const useZip = process.env.AUTOSCRIPTOR_ELECTRON_ZIP === '1';

let winTarget;
if (useNsis) {
  winTarget = [{ target: 'nsis', arch: ['x64'] }];
} else if (useZip) {
  winTarget = [{ target: 'zip', arch: ['x64'] }];
} else {
  winTarget = [{ target: 'portable', arch: ['x64'] }];
}

const config = {
  appId: 'com.autoscriptor.app',
  productName: '造笔',
  copyright: '造笔 AutoScriptor',

  directories: {
    output: '../dist_electron',
    buildResources: 'buildResources',
  },

  files: [
    'main.js',
    'preload.js',
    'install-packaged.cjs',
    'mumu-detect.cjs',
    'icon.png',
    'icon.ico',
    'renderer/**',
    'node_modules/tree-kill/**',
    'node_modules/yauzl/**',
    'node_modules/buffer-crc32/**',
    'node_modules/pend/**',
    '!**/*.map',
  ],

  extraFiles: [
    {
      from: '../dist/data/',
      to: './data/',
      filter: ['**/*', '!**/accounts/**/*.json'],
    },
    {
      from: '../dist/license/',
      to: './license/',
      filter: ['**/*'],
    },
    {
      from: '../dist/backend.zip',
      to: 'backend.zip',
    },
  ],

  win: {
    target: winTarget,
    icon: 'buildResources/icon.ico',
    signAndEditExecutable: false,
    ...(useZip && !useNsis
      ? {
          artifactName: 'AutoScriptor_Zao_${version}.${ext}',
        }
      : {}),
  },
};

if (!useNsis && !useZip) {
  config.portable = {
    artifactName: 'AutoScriptor_Zao_Install_${version}.exe',
  };
}

if (useNsis) {
  config.nsis = {
    oneClick: false,
    allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    shortcutName: '造笔',
    installerIcon: 'buildResources/icon.ico',
    uninstallerIcon: 'buildResources/icon.ico',
    artifactName: 'AutoScriptor_Zao_installer_${version}.exe',
    compression: nsisCompression,
  };
}

module.exports = config;
