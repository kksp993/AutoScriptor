'use strict';
/**
 * 从 icon.png / icon.ico 生成 buildResources/icon.ico（NSIS / win.icon 需要）。
 * 由 prepare-release-shell 与 npm prebuild 调用。
 */
const fs = require('fs');
const fsp = fs.promises;
const path = require('path');

const WEBAPP = path.join(__dirname, '..');

async function ensureInstallerIco() {
  const br = path.join(WEBAPP, 'buildResources');
  const outIco = path.join(br, 'icon.ico');
  const rootIco = path.join(WEBAPP, 'icon.ico');
  const iconPng = path.join(WEBAPP, 'icon.png');
  if (fs.existsSync(rootIco)) {
    await fsp.mkdir(br, { recursive: true });
    await fsp.copyFile(rootIco, outIco);
    return;
  }
  if (!fs.existsSync(iconPng)) return;
  const { default: pngToIco } = await import('png-to-ico');
  const buf = await pngToIco(iconPng);
  await fsp.mkdir(br, { recursive: true });
  await fsp.writeFile(outIco, buf);
}

module.exports = { ensureInstallerIco };

if (require.main === module) {
  ensureInstallerIco().catch((e) => {
    process.stderr.write(String(e && e.stack ? e.stack : e) + '\n');
    process.exit(1);
  });
}
