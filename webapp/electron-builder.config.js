/**
 * AutoScriptor Electron Builder Config
 * Output: dist/AutoScriptor-Setup.exe (NSIS installer) + dist/AutoScriptor-Portable.exe
 */

const config = {
  appId: 'com.autoscriptor.app',
  productName: '造笔',
  copyright: '造笔 AutoScriptor',

  directories: {
    output: '../dist_electron',
    buildResources: 'buildResources',
  },

  // Files to include in the package
  files: [
    'main.js',
    'preload.js',
    'icon.png',
    'icon.ico',
    'renderer/**',
    'node_modules/**',
    '!node_modules/.cache/**',
  ],

  // Extra files to copy to the app root (alongside the Electron binary)
  extraFiles: [
    // Exclude large Python/dev dirs from the bundle
    // The app expects Python to be pre-installed (.venv) at the project root
    {
      from: '../',
      to: './',
      filter: [
        'gui.py',
        'config.json',
        'config template.json',
        'AutoScriptor/**',
        'ZmxyOL/**',
        'services/**',
        'requirements.txt',
        '!**/__pycache__/**',
        '!**/*.pyc',
        '!**/node_modules/**',
        '!**/.git/**',
        '!**/logs/**',
        '!**/docs/**',
        '!**/.venv/**',
        '!**/.pytest_cache/**',
      ],
    },
  ],

  win: {
    target: [
      { target: 'nsis',     arch: ['x64'] },
      { target: 'portable', arch: ['x64'] },
    ],
    icon: 'buildResources/icon.ico',
    // 避免拉取 winCodeSign 并在解压时创建符号链接（无开发者模式/非管理员会失败）
    signAndEditExecutable: false,
  },

  nsis: {
    oneClick: false,
    allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    shortcutName: '造笔',
    installerIcon: 'buildResources/icon.ico',
    uninstallerIcon: 'buildResources/icon.ico',
    compression: 'normal',
  },

  portable: {
    artifactName: 'AutoScriptor-Portable.exe',
  },
};

module.exports = config;
