'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { execFileSync } = require('child_process');

const {
  runPackagedInstall,
  applyBackendIncremental,
  dryRunPackagedInstall,
  dryRunApplyBackendIncremental,
  __test,
} = require('../install-packaged.cjs');
const mumuDetect = require('../mumu-detect.cjs');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function assertIncludes(haystack, needle, message) {
  assert(String(haystack).includes(needle), message || `expected ${haystack} to include ${needle}`);
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
  const utf8Prelude = '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [Console]::OutputEncoding;';
  execFileSync(
    'powershell.exe',
    ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', `${utf8Prelude} ${command}`],
    { stdio: ['ignore', 'pipe', 'pipe'], encoding: 'utf8', windowsHide: true, timeout: 30000 },
  );
}

function powershellOutput(command) {
  const utf8Prelude = '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [Console]::OutputEncoding;';
  return execFileSync(
    'powershell.exe',
    ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', `${utf8Prelude} ${command}`],
    { stdio: ['ignore', 'pipe', 'pipe'], encoding: 'utf8', windowsHide: true, timeout: 60000 },
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

function validPackagedConfig(name) {
  return {
    app: {
      app_to_start: 'org.yjmobile.zmxy',
      auto_start: true,
      max_retry: 2,
      name: 'ZmxyOL',
      restart_on_error: true,
      run_in_background: false,
      debug_mode: true,
      cpu_cores: 4,
    },
    ocr: { use_gpu: false },
    emulator: {
      index: 0,
      adb_addr: '127.0.0.1:16384',
      mumu_folder: 'YOUR_MUMU_FOLDER, e.g.C:/Program Files/Netease/MuMu',
      emu_path: 'YOUR_EMU_PATH, e.g.C:/Program Files/Netease/MuMu/nx_main/MuMuManager.exe',
      adb_path: 'YOUR_ADB_PATH, e.g.C:/Program Files/Netease/MuMu/nx_main/adb.exe',
      post_execution: 'none',
    },
    llm: { use_agent: false, url: 'http://localhost:11434/v1', model: 'test' },
    scheduler: { auto_start: false },
    deploy: { log_level: 'info', theme: 'dark', password: null },
    notify: { enabled: false, config_yaml: 'provider: null' },
    update: { auto_check: true, check_interval_minutes: 30, auto_restart_time: null },
    remote_access: { enabled: false, ssh_server: null, ssh_user: null, ssh_executable: 'ssh' },
    accounts: { dir: '' },
    current_account: 'default',
    news: { account: 'fixture', password: name },
  };
}

function makeZipFromDir(srcDir, zipPath) {
  fs.rmSync(zipPath, { force: true });
  powershell(
    `$ErrorActionPreference='Stop'; Push-Location -LiteralPath ${psQuote(srcDir)}; `
    + `try { Compress-Archive -Path * -DestinationPath ${psQuote(zipPath)} -Force } finally { Pop-Location }`,
  );
  assert(fs.existsSync(zipPath), `zip was not created: ${zipPath}`);
}

function createReleaseFixture(tmp, name, options = {}) {
  const exeDir = path.join(tmp, `release-${name}`);
  const zipSrc = path.join(exeDir, '_backend-src');
  const zipPath = path.join(exeDir, 'backend.zip');
  fs.rmSync(exeDir, { recursive: true, force: true });
  mkdirp(zipSrc);

  const includeEngine = options.includeEngine !== false;
  if (includeEngine) writeText(path.join(zipSrc, 'autoscriptor-engine.exe'), `engine ${name}\n`);
  writeText(path.join(zipSrc, 'lib', 'version.txt'), `backend ${name}\n`);
  if (options.includeOldOnly !== false) {
    writeText(path.join(zipSrc, 'old-only.txt'), `remove on upgrade ${name}\n`);
  }
  if (options.extraBackendFiles) {
    for (const [rel, text] of Object.entries(options.extraBackendFiles)) {
      writeText(path.join(zipSrc, rel), text);
    }
  }
  makeZipFromDir(zipSrc, zipPath);

  const dataRoot = path.join(exeDir, 'data');
  const cfg = options.config || validPackagedConfig(name);
  writeText(path.join(dataRoot, 'config template.json'), JSON.stringify(cfg, null, 2));
  writeText(path.join(dataRoot, 'config.json'), JSON.stringify(cfg, null, 2));
  writeText(path.join(dataRoot, 'accounts', '.gitkeep'), '');
  writeText(path.join(dataRoot, 'custom_task', 'packaged.py'), `# packaged ${name}\n`);
  writeText(path.join(dataRoot, 'battle_character', 'hero.py'), `# battle character ${name}\n`);
  writeText(path.join(dataRoot, 'battle_character', 'packaged.json'), JSON.stringify({ name }, null, 2));
  writeText(path.join(dataRoot, 'assets', 'config', 'ui_map.csv'), 'key,text,left,top,width,height,img\n');
  writeText(path.join(dataRoot, 'assets', 'pic', '.gitkeep'), '');
  writeText(path.join(dataRoot, 'common', 'packaged.txt'), `common ${name}\n`);

  const portableExe = path.join(exeDir, 'AutoScriptor-Portable.exe');
  fs.writeFileSync(portableExe, Buffer.from(`portable ${name}\n`, 'utf8'));
  return { exeDir, zipPath, portableExe };
}

function createIncrementalZip(tmp, name, manifest, files) {
  const src = path.join(tmp, `incremental-${name}`);
  const zipPath = path.join(tmp, `backend_incremental_${name}.zip`);
  fs.rmSync(src, { recursive: true, force: true });
  mkdirp(src);
  writeText(path.join(src, 'incremental_manifest.json'), JSON.stringify(manifest, null, 2));
  for (const [rel, text] of Object.entries(files)) {
    writeText(path.join(src, rel), text);
  }
  makeZipFromDir(src, zipPath);
  return zipPath;
}

function assertNoBackendStaging(installRoot) {
  const leftovers = fs.readdirSync(installRoot).filter((name) => (
    name.startsWith('.backend.new.')
    || name.startsWith('.backend.incremental.')
    || name.includes('.bak.')
  ));
  assert(leftovers.length === 0, `backend staging leftovers: ${leftovers.join(', ')}`);
}

function parsePowerShellScript(ps1Path) {
  powershell(
    `$ErrorActionPreference='Stop'; `
    + `$null = [scriptblock]::Create((Get-Content -Raw -LiteralPath ${psQuote(ps1Path)}))`,
  );
}

function waitUntil(predicate, timeoutMs, message) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (predicate()) return;
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 250);
  }
  throw new Error(message || 'timed out waiting for condition');
}

function testMumuInfoMappingHelpers() {
  const helpers = mumuDetect.__test;
  const rows = helpers.parseMumuInfoPayload(JSON.stringify({
    0: {
      index: '0',
      is_main: true,
      is_process_started: true,
      adb_host_ip: '127.0.0.1',
      adb_port: 16384,
    },
    1: {
      index: '1',
      is_main: false,
      is_process_started: true,
      adb_host_ip: '127.0.0.1',
      adb_port: 16416,
    },
  }));

  assert(rows.length === 2, 'MuMu info parser should support keyed object payloads');
  assert(helpers.playerSerial(rows[1]) === '127.0.0.1:16416', 'player serial should use adb_host_ip:adb_port');
  assert(helpers.findPlayerBySerial(rows, '127.0.0.1:16416').index === '1', 'serial must map to matching MuMu index');
  assert(helpers.findPlayerBySerial(rows, 'localhost:16384').index === '0', 'localhost serial should normalize to 127.0.0.1');
}

async function testDryRunAndInvalidTargets(tmp) {
  const release = createReleaseFixture(tmp, 'v1');
  const installRoot = path.join(tmp, 'dry-run-install');
  const userDataPath = path.join(tmp, 'dry-run-userdata');

  const report = await dryRunPackagedInstall({
    installRoot,
    exeDir: release.exeDir,
    resourcesPath: release.exeDir,
    zipPath: release.zipPath,
    portableExePath: release.portableExe,
    appVersion: '1.2.3',
    userDataPath,
  });
  assert(report.ok, `dry-run should pass: ${JSON.stringify(report.errors)}`);
  assert(!fs.existsSync(installRoot), 'dry-run must not create install root');
  assert(!fs.existsSync(path.join(userDataPath, 'install.json')), 'dry-run must not write install marker');
  assert(report.plan && report.plan.sideEffects.some((s) => s.includes('dry-run')), 'dry-run report should describe no side effects');

  const dirtyRoot = path.join(tmp, 'dirty-root');
  mkdirp(dirtyRoot);
  writeText(path.join(dirtyRoot, 'random.txt'), 'unmanaged');
  const dirtyReport = await dryRunPackagedInstall({
    installRoot: dirtyRoot,
    exeDir: release.exeDir,
    zipPath: release.zipPath,
    portableExePath: release.portableExe,
    userDataPath,
  });
  assert(!dirtyReport.ok, 'dry-run must reject unmanaged non-empty install roots');
  await assertRejects(
    () => runPackagedInstall({
      installRoot: dirtyRoot,
      exeDir: release.exeDir,
      resourcesPath: release.exeDir,
      zipPath: release.zipPath,
      portableExePath: release.portableExe,
      userDataPath,
      skipMumuConfig: true,
      skipRegistry: true,
    }),
    /目录不为空|not empty|非空/,
    'actual installer must reject unmanaged non-empty install roots',
  );

  const badRelease = createReleaseFixture(tmp, 'bad-no-engine', { includeEngine: false });
  const badInstallRoot = path.join(tmp, 'bad-install');
  const badReport = await dryRunPackagedInstall({
    installRoot: badInstallRoot,
    exeDir: badRelease.exeDir,
    zipPath: badRelease.zipPath,
    portableExePath: badRelease.portableExe,
    userDataPath,
  });
  assert(!badReport.ok, 'dry-run must reject backend.zip without engine');
  assert(badReport.errors.some((e) => String(e).includes('autoscriptor-engine.exe')), 'dry-run should name missing engine');
  await assertRejects(
    () => runPackagedInstall({
      installRoot: badInstallRoot,
      exeDir: badRelease.exeDir,
      resourcesPath: badRelease.exeDir,
      zipPath: badRelease.zipPath,
      portableExePath: badRelease.portableExe,
      userDataPath,
      skipMumuConfig: true,
      skipRegistry: true,
    }),
    /autoscriptor-engine\.exe/,
    'actual installer must reject backend.zip without engine',
  );
  assert(!fs.existsSync(badInstallRoot), 'failed package validation should not create install root');

  const badConfigRelease = createReleaseFixture(tmp, 'bad-config', { config: { emulator: {} } });
  const badConfigRoot = path.join(tmp, 'bad-config-install');
  const badConfigReport = await dryRunPackagedInstall({
    installRoot: badConfigRoot,
    exeDir: badConfigRelease.exeDir,
    zipPath: badConfigRelease.zipPath,
    portableExePath: badConfigRelease.portableExe,
    userDataPath,
  });
  assert(!badConfigReport.ok, 'dry-run must reject packaged data with invalid config');
  assert(
    badConfigReport.errors.some((e) => String(e).includes('runtime data validation failed')),
    'dry-run should report runtime data validation failure',
  );
  await assertRejects(
    () => runPackagedInstall({
      installRoot: badConfigRoot,
      exeDir: badConfigRelease.exeDir,
      resourcesPath: badConfigRelease.exeDir,
      zipPath: badConfigRelease.zipPath,
      portableExePath: badConfigRelease.portableExe,
      userDataPath,
      skipMumuConfig: true,
      skipRegistry: true,
    }),
    /runtime data validation failed/,
    'actual installer must reject packaged data with invalid config',
  );
  assert(!fs.existsSync(badConfigRoot), 'failed runtime data validation should not create install root');

  assert(__test.safeJoin(tmp, 'safe/path.txt').startsWith(tmp), 'safeJoin should accept normal relative paths');
  assertRejects(() => Promise.resolve(__test.safeJoin(tmp, '../evil.txt')), /非法|zip/i);
}

async function testInstallRepairAndUninstallScript(tmp) {
  const releaseV1 = createReleaseFixture(tmp, 'v1');
  const releaseV2 = createReleaseFixture(tmp, 'v2', {
    includeOldOnly: false,
    extraBackendFiles: { 'lib/new-full.txt': 'new full install file\n' },
  });
  const installRoot = path.join(tmp, 'install-root');
  const userDataPath = path.join(tmp, 'userdata');
  const send = () => {};

  await runPackagedInstall({
    installRoot,
    exeDir: releaseV1.exeDir,
    resourcesPath: releaseV1.exeDir,
    zipPath: releaseV1.zipPath,
    portableExePath: releaseV1.portableExe,
    appVersion: '1.0.0',
    userDataPath,
    skipMumuConfig: true,
    skipRegistry: true,
    send,
  });

  assert(fs.existsSync(path.join(installRoot, 'backend', 'autoscriptor-engine.exe')), 'engine should be installed');
  assertIncludes(readText(path.join(installRoot, 'backend', 'lib', 'version.txt')), 'v1', 'backend v1 should be installed');
  assert(fs.existsSync(path.join(installRoot, '造笔.exe')), 'daily launcher should be copied');
  assert(!fs.existsSync(path.join(installRoot, 'config.json')), 'runtime config must stay in user dataRoot, not install root');
  assert(fs.existsSync(path.join(installRoot, 'Uninstall.ps1')), 'uninstall ps1 should be written');
  assert(fs.existsSync(path.join(installRoot, '卸载造笔.bat')), 'keep-data uninstall bat should be written');
  assert(fs.existsSync(path.join(installRoot, '彻底卸载造笔.bat')), 'remove-all uninstall bat should be written');
  const marker = JSON.parse(readText(path.join(userDataPath, 'install.json')));
  const runtimeDataRoot = path.join(path.resolve(userDataPath), 'data');
  assert(marker.installRoot === path.resolve(installRoot), 'install marker should contain installRoot');
  assert(marker.dataRoot === runtimeDataRoot, 'install marker should contain writable user dataRoot');
  parsePowerShellScript(path.join(installRoot, 'Uninstall.ps1'));
  assertIncludes(readText(path.join(installRoot, 'Uninstall.ps1')), 'ProcessId -ne $PID', 'uninstaller must not kill its own PowerShell process');
  assertIncludes(readText(path.join(installRoot, 'Uninstall.ps1')), 'ZaoBiUninstall-', 'uninstaller should launch a temp worker outside install root');
  assertIncludes(readText(path.join(__dirname, '..', 'install-packaged.cjs')), '$dataRoot', 'remove-all uninstaller should know external dataRoot');
  assertIncludes(readText(path.join(__dirname, '..', 'install-packaged.cjs')), "New-ItemProperty -LiteralPath $key", 'uninstall registry should write typed registry values');
  assertIncludes(readText(path.join(__dirname, '..', 'install-packaged.cjs')), "Set-RegDword 'EstimatedSize'", 'Windows Apps entry should include estimated size');
  assertIncludes(readText(path.join(installRoot, 'Uninstall.ps1')), 'Split-Path -Leaf $_.ExecutablePath', 'uninstaller should stop temporary portable app processes by executable name');
  assertIncludes(readText(path.join(installRoot, '彻底卸载造笔.bat')), '-RemoveUserData', 'remove-all bat should request user data removal');

  const userCfg = validPackagedConfig('user-kept');
  userCfg.user_marker = 'kept';
  userCfg.accounts.dir = path.join(tmp, 'external-accounts');
  delete userCfg.deploy;
  delete userCfg.update;
  writeText(path.join(runtimeDataRoot, 'config.json'), '\ufeff' + JSON.stringify(userCfg, null, 2));
  writeText(path.join(runtimeDataRoot, 'accounts', 'default.json'), JSON.stringify({ userAccount: 'kept' }, null, 2));
  writeText(path.join(runtimeDataRoot, 'custom_task', 'packaged.py'), '# user custom kept\n');
  writeText(path.join(runtimeDataRoot, 'battle_character', 'packaged.json'), JSON.stringify({ userBattle: 'kept' }, null, 2));

  const repairDryRun = await dryRunPackagedInstall({
    installRoot,
    exeDir: releaseV2.exeDir,
    resourcesPath: releaseV2.exeDir,
    zipPath: releaseV2.zipPath,
    portableExePath: releaseV2.portableExe,
    appVersion: '2.0.0',
    userDataPath,
  });
  assert(repairDryRun.ok, `repair dry-run should pass with legacy user config: ${JSON.stringify(repairDryRun.errors)}`);
  assert(
    repairDryRun.plan.runtime.configDefaults.willWrite,
    'repair dry-run should report missing config defaults that will be written',
  );
  assert(
    repairDryRun.plan.runtime.configDefaults.missingKeys.includes('deploy'),
    'repair dry-run should name missing deploy defaults',
  );

  await runPackagedInstall({
    installRoot,
    exeDir: releaseV2.exeDir,
    resourcesPath: releaseV2.exeDir,
    zipPath: releaseV2.zipPath,
    portableExePath: releaseV2.portableExe,
    appVersion: '2.0.0',
    userDataPath,
    skipMumuConfig: true,
    skipRegistry: true,
    send,
  });

  assertIncludes(readText(path.join(installRoot, 'backend', 'lib', 'version.txt')), 'v2', 'repair install should replace backend');
  assert(fs.existsSync(path.join(installRoot, 'backend', 'lib', 'new-full.txt')), 'repair install should install new backend files');
  assert(!fs.existsSync(path.join(installRoot, 'backend', 'old-only.txt')), 'repair install should remove stale backend files');
  const repairedConfig = JSON.parse(readText(path.join(runtimeDataRoot, 'config.json')));
  assert(repairedConfig.user_marker === 'kept', 'config user values should be preserved');
  assert(repairedConfig.accounts.dir === userCfg.accounts.dir, 'absolute external accounts dir should be preserved for existing user config');
  assert(repairedConfig.deploy && repairedConfig.deploy.theme === 'dark', 'missing deploy defaults should be added from packaged template');
  assert(repairedConfig.update && repairedConfig.update.auto_check === true, 'missing update defaults should be added from packaged template');
  assertIncludes(readText(path.join(runtimeDataRoot, 'accounts', 'default.json')), 'userAccount', 'account json should be preserved');
  assertIncludes(readText(path.join(runtimeDataRoot, 'custom_task', 'packaged.py')), 'user custom', 'custom task should be preserved');
  assertIncludes(readText(path.join(runtimeDataRoot, 'battle_character', 'packaged.json')), 'userBattle', 'battle character data should be preserved');
  assertIncludes(readText(path.join(runtimeDataRoot, 'common', 'packaged.txt')), 'v2', 'unprotected packaged data should update');
  assertNoBackendStaging(installRoot);
}

async function testWindowsAppsUninstallEntryCanUninstall(tmp) {
  const release = createReleaseFixture(tmp, 'apps-uninstall');
  const installRoot = path.join(tmp, 'apps-uninstall-root');
  const userDataPath = path.join(tmp, 'apps-uninstall-userdata');
  const registryKey = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\AutoScriptorZaoTest_' + process.pid;
  const registryKeyPs = psQuote(registryKey);

  try {
    await runPackagedInstall({
      installRoot,
      exeDir: release.exeDir,
      resourcesPath: release.exeDir,
      zipPath: release.zipPath,
      portableExePath: release.portableExe,
      appVersion: '9.9.9',
      userDataPath,
      skipMumuConfig: true,
      registryKey,
      send: () => {},
    });

    const uninstallString = powershellOutput(
      `$ErrorActionPreference='Stop'; `
      + `$item = Get-ItemProperty -LiteralPath ${registryKeyPs}; `
      + '@($item.DisplayName, $item.DisplayVersion, $item.InstallLocation, $item.UninstallString, $item.EstimatedSize, $item.NoModify, $item.NoRepair) -join "`n"',
    ).trim().split(/\r?\n/);
    assert(uninstallString[0] === '造笔', 'Windows Apps entry should have DisplayName');
    assert(uninstallString[1] === '9.9.9', 'Windows Apps entry should have DisplayVersion');
    assert(path.resolve(uninstallString[2]) === path.resolve(installRoot), 'Windows Apps entry should have InstallLocation');
    assertIncludes(uninstallString[3], 'powershell.exe', 'UninstallString should invoke PowerShell');
    assertIncludes(uninstallString[3], 'Uninstall.ps1', 'UninstallString should invoke the installed uninstall launcher');
    assert(Number(uninstallString[4]) > 0, 'Windows Apps entry should have EstimatedSize');
    assert(uninstallString[5] === '1', 'Windows Apps entry should disable Modify');
    assert(uninstallString[6] === '1', 'Windows Apps entry should disable Repair');

    powershell(`$ErrorActionPreference='Stop'; cmd.exe /c ${psQuote(uninstallString[3])}`);
    waitUntil(
      () => !fs.existsSync(path.join(installRoot, 'backend'))
        && !fs.existsSync(path.join(installRoot, 'Uninstall.ps1'))
        && !fs.existsSync(path.join(installRoot, '造笔.exe')),
      30000,
      'Windows Apps UninstallString did not remove installed app files',
    );
    waitUntil(
      () => !fs.existsSync(path.join(userDataPath, 'install.json')),
      30000,
      'Windows Apps UninstallString did not remove install marker',
    );
    powershell(`if (Test-Path -LiteralPath ${registryKeyPs}) { throw 'test uninstall registry key still exists' }`);
    assert(fs.existsSync(path.join(userDataPath, 'data', 'config.json')), 'default uninstall should preserve external dataRoot');
  } finally {
    powershell(`if (Test-Path -LiteralPath ${registryKeyPs}) { Remove-Item -LiteralPath ${registryKeyPs} -Recurse -Force -ErrorAction SilentlyContinue }`);
  }
}

async function testInstallProgressIsThrottled(tmp) {
  const extraBackendFiles = {};
  for (let i = 0; i < 360; i++) {
    extraBackendFiles[`bulk/file-${String(i).padStart(4, '0')}.txt`] = `bulk ${i}\n`;
  }

  const release = createReleaseFixture(tmp, 'progress', { extraBackendFiles });
  const installRoot = path.join(tmp, 'progress-install');
  const userDataPath = path.join(tmp, 'progress-userdata');
  const events = [];

  await runPackagedInstall({
    installRoot,
    exeDir: release.exeDir,
    resourcesPath: release.exeDir,
    zipPath: release.zipPath,
    portableExePath: release.portableExe,
    appVersion: '1.0.0',
    userDataPath,
    skipMumuConfig: true,
    skipRegistry: true,
    send: (data) => events.push(data),
  });

  const extractLogs = events.filter((e) => e.type === 'log' && String(e.message || '').startsWith('[解压] '));
  const extractProgress = events.filter((e) => e.type === 'progress' && String(e.message || '').startsWith('解压 '));
  assert(extractLogs.length < 60, `extract logs should be throttled, got ${extractLogs.length}`);
  assert(extractProgress.length < 150, `extract progress should be throttled, got ${extractProgress.length}`);
  assert(events.some((e) => e.type === 'complete'), 'installer should emit complete');
  assert(
    fs.existsSync(path.join(installRoot, 'backend', 'bulk', 'file-0359.txt')),
    'bulk backend fixture should be installed',
  );
  assertNoBackendStaging(installRoot);
}

async function testIncrementalUpdateAndRollback(tmp) {
  const release = createReleaseFixture(tmp, 'base');
  const installRoot = path.join(tmp, 'incremental-install');
  const rollbackRoot = path.join(tmp, 'incremental-rollback');
  const userDataPath = path.join(tmp, 'incremental-userdata');
  const send = () => {};

  const installOpts = (root) => ({
    installRoot: root,
    exeDir: release.exeDir,
    resourcesPath: release.exeDir,
    zipPath: release.zipPath,
    portableExePath: release.portableExe,
    appVersion: '1.0.0',
    userDataPath: path.join(userDataPath, path.basename(root)),
    skipMumuConfig: true,
    skipRegistry: true,
    send,
  });
  await runPackagedInstall(installOpts(installRoot));
  await runPackagedInstall(installOpts(rollbackRoot));

  const oldVersion = 'backend base\n';
  const newVersion = 'backend incremental\n';
  const newFile = 'added by incremental\n';
  const manifest = {
    format: 'backend_incremental_v1',
    from_label: 'base',
    to_label: 'incremental',
    remove: ['old-only.txt'],
    entries: [
      {
        action: 'replace',
        path: 'lib/version.txt',
        old_sha256: sha256Text(oldVersion),
        new_sha256: sha256Text(newVersion),
      },
      {
        action: 'add',
        path: 'lib/added.txt',
        new_sha256: sha256Text(newFile),
      },
    ],
  };
  const incZip = createIncrementalZip(tmp, 'ok', manifest, {
    'lib/version.txt': newVersion,
    'lib/added.txt': newFile,
  });

  const dryInc = await dryRunApplyBackendIncremental({ installRoot, zipPath: incZip });
  assert(dryInc.ok, `incremental dry-run should pass: ${JSON.stringify(dryInc.errors)}`);
  assert(dryInc.plan.replace === 1 && dryInc.plan.add === 1 && dryInc.plan.remove === 1, 'incremental dry-run should count actions');

  await applyBackendIncremental({ installRoot, zipPath: incZip, send });
  assert(readText(path.join(installRoot, 'backend', 'lib', 'version.txt')) === newVersion, 'incremental should replace file');
  assert(readText(path.join(installRoot, 'backend', 'lib', 'added.txt')) === newFile, 'incremental should add file');
  assert(!fs.existsSync(path.join(installRoot, 'backend', 'old-only.txt')), 'incremental should remove old file');
  assertNoBackendStaging(installRoot);

  const badManifest = {
    ...manifest,
    entries: [
      {
        action: 'replace',
        path: 'lib/version.txt',
        old_sha256: sha256Text('wrong baseline\n'),
        new_sha256: sha256Text(newVersion),
      },
    ],
  };
  const badZip = createIncrementalZip(tmp, 'bad-baseline', badManifest, {
    'lib/version.txt': newVersion,
  });
  const dryBad = await dryRunApplyBackendIncremental({ installRoot: rollbackRoot, zipPath: badZip });
  assert(!dryBad.ok, 'incremental dry-run must reject baseline mismatch');
  await assertRejects(
    () => applyBackendIncremental({ installRoot: rollbackRoot, zipPath: badZip, send }),
    /基线不匹配|baseline/i,
    'actual incremental update must reject baseline mismatch',
  );
  assert(readText(path.join(rollbackRoot, 'backend', 'lib', 'version.txt')) === oldVersion, 'failed incremental should preserve old backend');
  assertNoBackendStaging(rollbackRoot);
}

async function main() {
  if (process.platform !== 'win32') {
    console.log('[installer-test] skipped: Windows PowerShell/Compress-Archive required');
    return;
  }

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'autoscriptor-installer-test-'));
  const keep = !!process.env.KEEP_INSTALLER_TESTS;
  try {
    testMumuInfoMappingHelpers();
    await testDryRunAndInvalidTargets(tmp);
    await testInstallRepairAndUninstallScript(tmp);
    await testWindowsAppsUninstallEntryCanUninstall(tmp);
    await testInstallProgressIsThrottled(tmp);
    await testIncrementalUpdateAndRollback(tmp);
    console.log('[installer-test] OK');
    console.log(`[installer-test] temp root ${keep ? 'kept' : 'removed'}:`, tmp);
  } finally {
    if (!keep) {
      fs.rmSync(tmp, { recursive: true, force: true });
    }
  }
}

main().catch((e) => {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
