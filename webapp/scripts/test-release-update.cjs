'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { execFileSync } = require('child_process');

const {
  dryRunLocalReleaseUpdate,
  applyLocalReleaseUpdate,
} = require('../release-update.cjs');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function assertRejects(fn, pattern, message) {
  let rejected = false;
  try {
    await fn();
  } catch (e) {
    rejected = true;
    if (pattern && !pattern.test(String(e && e.message ? e.message : e))) {
      throw new Error(message || `unexpected rejection: ${e && e.message ? e.message : e}`);
    }
  }
  if (!rejected) throw new Error(message || 'expected function to reject');
}

function psQuote(value) {
  return "'" + String(value).replace(/'/g, "''") + "'";
}

function powershell(command) {
  execFileSync(
    'powershell.exe',
    ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', command],
    { stdio: ['ignore', 'pipe', 'pipe'], encoding: 'utf8', windowsHide: true, timeout: 30000 },
  );
}

function mkdirp(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function writeText(file, text) {
  mkdirp(path.dirname(file));
  fs.writeFileSync(file, text, 'utf8');
}

function readText(file) {
  return fs.readFileSync(file, 'utf8');
}

function sha256Text(text) {
  return crypto.createHash('sha256').update(Buffer.from(text, 'utf8')).digest('hex');
}

function makeZipFromDir(srcDir, zipPath) {
  fs.rmSync(zipPath, { force: true });
  powershell(
    `$ErrorActionPreference='Stop'; Push-Location -LiteralPath ${psQuote(srcDir)}; `
    + `try { Compress-Archive -Path * -DestinationPath ${psQuote(zipPath)} -Force } finally { Pop-Location }`,
  );
  assert(fs.existsSync(zipPath), `zip was not created: ${zipPath}`);
}

function createInstalled(tmp, name, version = '1.1.0') {
  const installRoot = path.join(tmp, `install-${name}`);
  const userDataPath = path.join(tmp, `userdata-${name}`);
  const dataRoot = path.join(userDataPath, 'data');
  fs.rmSync(installRoot, { recursive: true, force: true });
  fs.rmSync(userDataPath, { recursive: true, force: true });
  writeText(path.join(installRoot, 'backend', 'autoscriptor-engine.exe'), 'old engine\n');
  writeText(path.join(installRoot, 'backend', 'services', 'webui', 'static', 'app.js'), 'old app\n');
  writeText(path.join(installRoot, '造笔.exe'), 'old launcher\n');
  writeText(path.join(dataRoot, 'accounts', 'default.json'), '{"kept":true}\n');
  writeText(path.join(dataRoot, 'custom_task', 'user.py'), '# user\n');
  writeText(path.join(dataRoot, 'battle_character', 'role.py'), '# role\n');
  writeText(
    path.join(dataRoot, 'config.json'),
    JSON.stringify({ app: { debug_mode: true }, deploy: { theme: 'dark' } }, null, 2),
  );
  writeText(
    path.join(userDataPath, 'install.json'),
    JSON.stringify({ installRoot, dataRoot, version }, null, 2),
  );
  return { installRoot, userDataPath, dataRoot };
}

function createUpdateZip(tmp, name, manifest, files) {
  const src = path.join(tmp, `update-src-${name}`);
  const zipPath = path.join(tmp, `AutoScriptor_Update_${name}.zip`);
  fs.rmSync(src, { recursive: true, force: true });
  mkdirp(src);
  writeText(path.join(src, 'update_manifest.json'), JSON.stringify(manifest, null, 2));
  for (const [rel, text] of Object.entries(files)) {
    writeText(path.join(src, rel), text);
  }
  makeZipFromDir(src, zipPath);
  return zipPath;
}

function manifestFor(targetVersion, entries = {}) {
  const engine = entries.engine || 'new engine\n';
  const app = entries.app || 'new app\n';
  const template = entries.template || '{"template":true}\n';
  const launcher = entries.launcher || '';
  const replace = [
    {
      path: 'backend/autoscriptor-engine.exe',
      sha256: sha256Text(engine),
    },
    {
      path: 'backend/services/webui/static/app.js',
      sha256: sha256Text(app),
    },
  ];
  if (launcher) {
    replace.push({
      path: '造笔.exe',
      sha256: sha256Text(launcher),
    });
  }
  return {
    format: 'autoscriptor_update_v1',
    compat_line: targetVersion.split('.').slice(0, 2).join('.'),
    base_version: `${targetVersion.split('.')[0]}.${targetVersion.split('.')[1]}.0`,
    target_version: targetVersion,
    mode: 'minor-cumulative',
    replace,
    mkdir: ['data/assets/cache'],
    copy_if_missing: [
      {
        path: 'data/templates/example.json',
        sha256: sha256Text(template),
      },
    ],
    config_defaults: {
      app: { debug_mode: false, new_flag: true },
      deploy: { content_manifest_url: 'https://updates.example/manifest.json' },
    },
  };
}

async function testCumulativeUpdateDryRunAndApply(tmp) {
  const { installRoot, userDataPath, dataRoot } = createInstalled(tmp, 'ok', '1.1.0');
  const configPath = path.join(dataRoot, 'config.json');
  writeText(configPath, '\ufeff' + readText(configPath));
  const engine = 'new engine\n';
  const app = 'new app\n';
  const template = '{"template":true}\n';
  const launcher = 'launcher 1.1.5\n';
  const zipPath = createUpdateZip(tmp, '1.1.5', manifestFor('1.1.5', { engine, app, template, launcher }), {
    'backend/autoscriptor-engine.exe': engine,
    'backend/services/webui/static/app.js': app,
    'data/templates/example.json': template,
    '造笔.exe': launcher,
  });

  const dry = await dryRunLocalReleaseUpdate({ installRoot, userDataPath, packagePath: zipPath });
  assert(dry.ok, `dry-run should pass: ${JSON.stringify(dry.errors)}`);
  assert(dry.currentVersion === '1.1.0', 'dry-run should read current version from install marker');
  assert(dry.targetVersion === '1.1.5', 'dry-run should report target version');
  assert(dry.compatLine === '1.1', 'dry-run should report compat line');
  assert(dry.plan.replace === 3, 'dry-run should count replacement files');
  assert(dry.plan.add === 1, 'dry-run should count copy_if_missing as add');
  assert(dry.plan.mkdir === 1, 'dry-run should count missing mkdir');
  assert(dry.plan.requiresBackendStop, 'engine replacement should require backend stop');
  assert(dry.plan.configDefaults.missingKeys.includes('app.new_flag'), 'dry-run should report missing config defaults');
  assert(readText(path.join(installRoot, 'backend', 'autoscriptor-engine.exe')) === 'old engine\n', 'dry-run must not modify engine');

  const result = await applyLocalReleaseUpdate({ installRoot, userDataPath, packagePath: zipPath, keepBackup: false });
  assert(result.ok, 'apply should succeed');
  assert(readText(path.join(installRoot, 'backend', 'autoscriptor-engine.exe')) === engine, 'engine should be replaced');
  assert(readText(path.join(installRoot, 'backend', 'services', 'webui', 'static', 'app.js')) === app, 'static file should be replaced');
  assert(readText(path.join(installRoot, '造笔.exe')) === launcher, 'daily launcher should be replaced');
  assert(readText(path.join(installRoot, 'data', 'templates', 'example.json')) === template, 'missing template should be copied');
  assert(fs.existsSync(path.join(installRoot, 'data', 'assets', 'cache')), 'mkdir should be applied');
  const cfg = JSON.parse(readText(path.join(dataRoot, 'config.json')));
  assert(cfg.app.debug_mode === true, 'config defaults must not overwrite user value');
  assert(cfg.app.new_flag === true, 'config defaults should add missing nested key');
  assert(cfg.deploy.content_manifest_url.includes('updates.example'), 'config defaults should add missing deploy key');
  assert(readText(path.join(dataRoot, 'accounts', 'default.json')).includes('kept'), 'accounts must be preserved');
  const marker = JSON.parse(readText(path.join(userDataPath, 'install.json')));
  assert(marker.version === '1.1.5', 'install marker version should be updated');
  assert(marker.dataRoot === dataRoot, 'install marker dataRoot should be preserved');
  const versionFile = JSON.parse(readText(path.join(installRoot, '.autoscriptor', 'release_version.json')));
  assert(versionFile.version === '1.1.5', 'install root version file should be updated');
}

async function testPatch101UpdateFrom100PreservesUserData(tmp) {
  const { installRoot, userDataPath, dataRoot } = createInstalled(tmp, 'patch-101', '1.0.0');
  const engine = 'engine 1.0.1\n';
  const app = 'app 1.0.1\n';
  const template = '{"template":"1.0.1"}\n';
  const zipPath = createUpdateZip(tmp, '1.0.1', manifestFor('1.0.1', { engine, app, template }), {
    'backend/autoscriptor-engine.exe': engine,
    'backend/services/webui/static/app.js': app,
    'data/templates/example.json': template,
  });

  const dry = await dryRunLocalReleaseUpdate({ installRoot, userDataPath, packagePath: zipPath });
  assert(dry.ok, `1.0.0 -> 1.0.1 dry-run should pass: ${JSON.stringify(dry.errors)}`);
  assert(dry.currentVersion === '1.0.0', 'dry-run should report 1.0.0 current version');
  assert(dry.targetVersion === '1.0.1', 'dry-run should report 1.0.1 target version');
  assert(dry.compatLine === '1.0', 'dry-run should stay on the 1.0 compatibility line');

  const result = await applyLocalReleaseUpdate({ installRoot, userDataPath, packagePath: zipPath, keepBackup: false });
  assert(result.ok, '1.0.0 -> 1.0.1 apply should succeed');
  assert(readText(path.join(installRoot, 'backend', 'autoscriptor-engine.exe')) === engine, 'engine should be updated to 1.0.1');
  assert(readText(path.join(dataRoot, 'accounts', 'default.json')).includes('kept'), 'accounts must be preserved on 1.0.1 update');
  assert(readText(path.join(dataRoot, 'custom_task', 'user.py')).includes('# user'), 'custom tasks must be preserved on 1.0.1 update');
  assert(readText(path.join(dataRoot, 'battle_character', 'role.py')).includes('# role'), 'battle character data must be preserved on 1.0.1 update');
  const marker = JSON.parse(readText(path.join(userDataPath, 'install.json')));
  assert(marker.version === '1.0.1', 'install marker version should be 1.0.1');
  const versionFile = JSON.parse(readText(path.join(installRoot, '.autoscriptor', 'release_version.json')));
  assert(versionFile.version === '1.0.1', 'install root version file should be 1.0.1');
}

async function testRejectsUnsafeVersionsAndPaths(tmp) {
  const base = createInstalled(tmp, 'reject', '1.0.9');
  const engine = 'new engine\n';
  const badLineZip = createUpdateZip(tmp, 'bad-line', manifestFor('1.1.5', { engine }), {
    'backend/autoscriptor-engine.exe': engine,
    'backend/services/webui/static/app.js': 'new app\n',
    'data/templates/example.json': '{"template":true}\n',
  });
  const badLine = await dryRunLocalReleaseUpdate({ ...base, packagePath: badLineZip });
  assert(!badLine.ok, 'dry-run should reject cross compat line update');

  const newer = createInstalled(tmp, 'newer', '1.1.6');
  const downgrade = await dryRunLocalReleaseUpdate({ ...newer, packagePath: badLineZip });
  assert(!downgrade.ok, 'dry-run should reject downgrade inside compat line');

  const protectedManifest = {
    format: 'autoscriptor_update_v1',
    compat_line: '1.1',
    base_version: '1.1.0',
    target_version: '1.1.5',
    replace: [{ path: 'data/config.json', sha256: sha256Text('evil\n') }],
  };
  const protectedZip = createUpdateZip(tmp, 'protected', protectedManifest, {
    'data/config.json': 'evil\n',
  });
  const protectedReport = await dryRunLocalReleaseUpdate({
    ...createInstalled(tmp, 'protected-install', '1.1.0'),
    packagePath: protectedZip,
  });
  assert(!protectedReport.ok, 'dry-run should reject protected user data paths');
}

async function testRollbackWhenLaterFileFails(tmp) {
  const { installRoot, userDataPath } = createInstalled(tmp, 'rollback', '1.1.0');
  writeText(path.join(installRoot, 'backend', 'conflict'), 'file blocks child dir\n');
  const engine = 'rollback new engine\n';
  const blocked = 'cannot write\n';
  const manifest = {
    format: 'autoscriptor_update_v1',
    compat_line: '1.1',
    base_version: '1.1.0',
    target_version: '1.1.5',
    replace: [
      { path: 'backend/autoscriptor-engine.exe', sha256: sha256Text(engine) },
      { path: 'backend/conflict/child.txt', sha256: sha256Text(blocked) },
    ],
  };
  const zipPath = createUpdateZip(tmp, 'rollback', manifest, {
    'backend/autoscriptor-engine.exe': engine,
    'backend/conflict/child.txt': blocked,
  });
  const dry = await dryRunLocalReleaseUpdate({ installRoot, userDataPath, packagePath: zipPath });
  assert(dry.ok, `dry-run should pass before runtime write failure: ${JSON.stringify(dry.errors)}`);
  await assertRejects(
    () => applyLocalReleaseUpdate({ installRoot, userDataPath, packagePath: zipPath }),
    /ENOTDIR|not a directory|移动失败|mkdir/i,
    'apply should fail when target parent is blocked',
  );
  assert(readText(path.join(installRoot, 'backend', 'autoscriptor-engine.exe')) === 'old engine\n', 'rollback should restore old engine');
}

async function testRejectsInvalidConfigBeforeDefaultsMerge(tmp) {
  const { installRoot, userDataPath, dataRoot } = createInstalled(tmp, 'bad-config', '1.1.0');
  writeText(path.join(dataRoot, 'config.json'), '{broken json');
  const engine = 'new engine\n';
  const app = 'new app\n';
  const template = '{"template":true}\n';
  const zipPath = createUpdateZip(tmp, 'bad-config', manifestFor('1.1.5', { engine, app, template }), {
    'backend/autoscriptor-engine.exe': engine,
    'backend/services/webui/static/app.js': app,
    'data/templates/example.json': template,
  });

  const dry = await dryRunLocalReleaseUpdate({ installRoot, userDataPath, packagePath: zipPath });
  assert(!dry.ok, 'dry-run should reject invalid data/config.json before config_defaults merge');
  assert(
    dry.errors.some((e) => String(e).includes('data/config.json is invalid')),
    'dry-run should name invalid config.json',
  );
  await assertRejects(
    () => applyLocalReleaseUpdate({ installRoot, userDataPath, packagePath: zipPath }),
    /data\/config\.json is invalid/i,
    'apply should reject invalid config before writing defaults',
  );
  assert(readText(path.join(dataRoot, 'config.json')) === '{broken json', 'invalid user config must be preserved');
}

async function main() {
  if (process.platform !== 'win32') {
    console.log('[release-update-test] skipped: Windows PowerShell/Compress-Archive required');
    return;
  }
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'autoscriptor-release-update-test-'));
  const keep = !!process.env.KEEP_INSTALLER_TESTS;
  try {
    await testCumulativeUpdateDryRunAndApply(tmp);
    await testPatch101UpdateFrom100PreservesUserData(tmp);
    await testRejectsUnsafeVersionsAndPaths(tmp);
    await testRollbackWhenLaterFileFails(tmp);
    await testRejectsInvalidConfigBeforeDefaultsMerge(tmp);
    console.log('[release-update-test] OK');
    console.log(`[release-update-test] temp root ${keep ? 'kept' : 'removed'}:`, tmp);
  } finally {
    if (!keep) fs.rmSync(tmp, { recursive: true, force: true });
  }
}

main().catch((e) => {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
