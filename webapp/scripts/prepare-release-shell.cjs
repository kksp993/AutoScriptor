'use strict';
const fs = require('fs');
const fsp = fs.promises;
const path = require('path');
const JavaScriptObfuscator = require('javascript-obfuscator');
const { minify } = require('html-minifier-terser');

const WEBAPP = path.join(__dirname, '..');
const STAGING = path.join(WEBAPP, '.release-staging');
const { ensureInstallerIco } = require('./ensure-ico.cjs');

const OBF_OPTS = {
  target: 'node',
  compact: true,
  controlFlowFlattening: true,
  controlFlowFlatteningThreshold: 0.45,
  deadCodeInjection: false,
  identifierNamesGenerator: 'hexadecimal',
  log: false,
  numbersToExpressions: true,
  renameGlobals: false,
  selfDefending: false,
  simplify: true,
  sourceMap: false,
  splitStrings: true,
  stringArray: true,
  stringArrayEncoding: ['base64'],
  stringArrayThreshold: 0.72,
  transformObjectKeys: true,
  unicodeEscapeSequence: false,
  reservedNames: ['^require$', '^exports$', '^module$', '__dirname', '__filename', 'process', 'Buffer'],
};

const HTML_MIN = {
  collapseWhitespace: true,
  removeComments: true,
  removeRedundantAttributes: true,
  removeScriptTypeAttributes: true,
  removeStyleLinkTypeAttributes: true,
  minifyCSS: true,
  minifyJS: true,
  keepClosingSlash: true,
};

async function rmrf(p) {
  await fsp.rm(p, { recursive: true, force: true });
}

async function obfuscateFile(rel) {
  const srcPath = path.join(WEBAPP, rel);
  const code = await fsp.readFile(srcPath, 'utf8');
  const out = JavaScriptObfuscator.obfuscate(code, OBF_OPTS).getObfuscatedCode();
  const outPath = path.join(STAGING, rel);
  await fsp.mkdir(path.dirname(outPath), { recursive: true });
  await fsp.writeFile(outPath, out, 'utf8');
}

async function minifyHtml(rel) {
  const srcPath = path.join(WEBAPP, rel);
  const raw = await fsp.readFile(srcPath, 'utf8');
  const out = await minify(raw, HTML_MIN);
  const outPath = path.join(STAGING, rel);
  await fsp.mkdir(path.dirname(outPath), { recursive: true });
  await fsp.writeFile(outPath, out, 'utf8');
}

async function copyIfPresent(rel) {
  const a = path.join(WEBAPP, rel);
  try {
    await fsp.access(a);
  } catch {
    return;
  }
  const b = path.join(STAGING, rel);
  await fsp.mkdir(path.dirname(b), { recursive: true });
  await fsp.copyFile(a, b);
}

async function copyTreeKill() {
  const src = path.join(WEBAPP, 'node_modules', 'tree-kill');
  const dst = path.join(STAGING, 'node_modules', 'tree-kill');
  await fsp.mkdir(path.dirname(dst), { recursive: true });
  await fsp.cp(src, dst, { recursive: true });
  const noise = ['README.md', 'readme.md', 'CHANGELOG.md', 'LICENSE', 'LICENSE.md'];
  for (const n of noise) {
    const p = path.join(dst, n);
    try {
      await fsp.unlink(p);
    } catch (_) {}
  }
}

async function copyNodeModule(name) {
  const src = path.join(WEBAPP, 'node_modules', name);
  try {
    await fsp.access(src);
  } catch {
    throw new Error(`缺少依赖包 ${name}（请在 webapp 目录执行 npm install）`);
  }
  const dst = path.join(STAGING, 'node_modules', name);
  await fsp.mkdir(path.dirname(dst), { recursive: true });
  await fsp.cp(src, dst, { recursive: true });
  const noise = ['README.md', 'readme.md', 'CHANGELOG.md', 'LICENSE', 'LICENSE.md'];
  for (const n of noise) {
    const p = path.join(dst, n);
    try {
      await fsp.unlink(p);
    } catch (_) {}
  }
}

async function copyPlainRequired(rel) {
  const a = path.join(WEBAPP, rel);
  try {
    await fsp.access(a);
  } catch {
    throw new Error(`缺少必需文件: ${rel}`);
  }
  const b = path.join(STAGING, rel);
  await fsp.mkdir(path.dirname(b), { recursive: true });
  await fsp.copyFile(a, b);
}

async function writePackageJson() {
  const base = JSON.parse(await fsp.readFile(path.join(WEBAPP, 'package.json'), 'utf8'));
  const minimal = {
    name: base.name,
    version: base.version,
    main: 'main.js',
    private: true,
    dependencies: base.dependencies || {},
  };
  await fsp.writeFile(
    path.join(STAGING, 'package.json'),
    JSON.stringify(minimal),
    'utf8',
  );
}

async function main() {
  await ensureInstallerIco();
  await rmrf(STAGING);
  await fsp.mkdir(STAGING, { recursive: true });

  await obfuscateFile('main.js');
  await obfuscateFile('preload.js');
  await minifyHtml(path.join('renderer', 'loading.html'));
  await minifyHtml(path.join('renderer', 'installer.html'));
  await copyIfPresent('icon.ico');
  await copyIfPresent('icon.png');
  await copyTreeKill();
  await copyNodeModule('yauzl');
  await copyNodeModule('buffer-crc32');
  await copyNodeModule('pend');
  await copyPlainRequired('install-packaged.cjs');
  await copyPlainRequired('mumu-detect.cjs');
  await writePackageJson();
}

main().catch((e) => {
  process.stderr.write(String(e && e.stack ? e.stack : e) + '\n');
  process.exit(1);
});
