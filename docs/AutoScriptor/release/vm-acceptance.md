# Release VM Acceptance

This document is the Windows VM lab plan for validating release artifacts. A release is not accepted until both the full installer and the same-line update package have been checked when both are produced.

Do not claim VM acceptance, update compatibility, or release readiness from local smoke tests alone. An interrupted build, a package that has not passed `npm run verify-pack`, or a package that has not been installed/upgraded in the VM is not an accepted release artifact.

VM acceptance is the final release gate. Do not push the release commit/tag to
GitHub, upload or publish artifacts, or tell users a version is released until
the required VM reports have been collected and reviewed. If the VM pass is
blocked or pending, the correct status is "artifacts built, release not
published/accepted".

## Minimal Snapshot Plan

Do not create many snapshots at first. Use:

1. `clean-base`: Windows installed, Guest Additions installed, shared folder works.
2. `after-install`: optional, only if a failure needs deeper inspection.

For each test round, restore `clean-base`, run the installer, collect logs, then restore again.

## Host Setup

Run from the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\release\vm_host_check.ps1
```

If no VM manager exists, install VirtualBox from Oracle's official download page, or with Chocolatey:

```powershell
choco install virtualbox -y
```

The Chocolatey command may require an elevated PowerShell window and UAC confirmation.

Download a Windows ISO only from Microsoft. A Windows 11 Enterprise evaluation ISO is suitable for disposable test VMs.

## Create The VM

```powershell
powershell -ExecutionPolicy Bypass -File scripts\release\vm_create_virtualbox_lab.ps1 `
  -IsoPath D:\ISO\Windows11.iso `
  -Start
```

Install Windows manually in the VM. After Windows setup:

1. Install VirtualBox Guest Additions.
2. Confirm `\\VBOXSVR\release` opens.
3. Take the clean snapshot:

```powershell
VBoxManage snapshot "AutoScriptor-Win-ReleaseLab" take clean-base
```

## Stage Release Artifacts

Copy these artifacts into the host shared folder before restoring the VM snapshot:

```text
\\VBOXSVR\release\AutoScriptor_Zao_Install_x.y.z.exe
\\VBOXSVR\release\AutoScriptor_Update_x.y.z.zip
```

If testing upgrade, also keep the previous same-line installer:

```text
\\VBOXSVR\release\AutoScriptor_Zao_Install_x.y.(z-1).exe
```

Record SHA-256 for every artifact in the release note or acceptance log.

## Full Installer Acceptance

When the release needs to prove the real user-facing installer, run the
portable exe by GUI interaction instead of the headless PowerShell path:

1. Restore `clean-base`.
2. Open `\\VBOXSVR\release` in Explorer and start
   `AutoScriptor_Zao_Install_x.y.z.exe`.
   If the portable exe exits immediately or never shows the Electron window
   when launched from the VirtualBox shared folder, copy it to a local guest
   path such as `%USERPROFILE%\Downloads` first, then launch that local copy by
   GUI/keyboard interaction. Do not assume a fixed mapped drive letter such as
   `Y:`; use `\\VBOXSVR\release` directly or let `pushd` create the temporary
   drive letter for that command.
3. Complete the HTML installer by keyboard/mouse injection or direct clicks,
   choosing a clean directory such as
   `%USERPROFILE%\Documents\AutoScriptorGuiInstall`.
   The primary wizard button must be keyboard reachable: when focus is not in an
   editable input control, Enter should trigger the current primary action. If a VM can
   show the installer but cannot advance without a mouse-only click path, treat
   that as an installer accessibility regression and fix it before publishing.
4. Keep screenshots for the selected path, install progress/completion, and
   the launched main window.
5. Verify the install tree contains `backend\autoscriptor-engine.exe`,
   `%APPDATA%\autoscriptor\install.json` points at the chosen install root,
   the daily launcher exists, and WebUI responds on `127.0.0.1:5000`.

The headless path below is still useful for repeatable installer hygiene and
log collection, but it is not a substitute when the requested acceptance target
is the real GUI flow.

Inside the VM:

```powershell
powershell -ExecutionPolicy Bypass -File \\VBOXSVR\release\vm_guest_acceptance.ps1 -Mode PreInstall
```

Complete the installer UI and choose:

```text
%LOCALAPPDATA%\AutoScriptorReleaseTest
```

Then run:

```powershell
powershell -ExecutionPolicy Bypass -File \\VBOXSVR\release\vm_guest_acceptance.ps1 -Mode PostInstall
```

Logs are written to:

```text
\\VBOXSVR\release\logs
```

For a less manual pass, use the headless installer path:

```powershell
powershell -ExecutionPolicy Bypass -File \\VBOXSVR\release\vm_guest_headless_install.ps1 `
  -PackagePath \\VBOXSVR\release\AutoScriptor_Zao_Install_x.y.z.exe `
  -InstallRoot "$env:USERPROFILE\Documents\AutoScriptor" `
  -SkipMumuConfig
```

Then run the normal post-install acceptance:

```powershell
powershell -ExecutionPolicy Bypass -File \\VBOXSVR\release\vm_guest_acceptance.ps1 `
  -Mode PostInstall `
  -InstallRoot "$env:USERPROFILE\Documents\AutoScriptor"
```

When launching a guest helper from Win+R or an injected `cmd.exe`, do not start a
batch file directly with `\\VBOXSVR\release\...` as the current directory.
`cmd.exe` prints a UNC warning and falls back to `C:\Windows`, which can make the
acceptance pass appear idle with empty logs. Wrap the command with `pushd` first:

```cmd
cmd /c "pushd \\VBOXSVR\release && call run_full_101.cmd"
```

If the app window is already visible and WebUI responds but `PostInstall` creates
an `acceptance_*` directory without `report.json`, inspect the diagnostics path
before rerunning the installer. The guest script must keep WMI/CIM process
enumeration bounded (`Get-CimInstance ... -OperationTimeoutSec 10`) so report
writing cannot hang after the actual WebUI check has succeeded.

Keep the VM result split by layer. A clean VirtualBox VM can prove installer
hygiene and basic WebUI startup while still failing Paddle/OCR imports, for
example `DLL initialization routine failed` for `paddle\base\libpaddle.pyd` or
`name 'libpaddle' is not defined`. Treat that as "basic WebUI accepted, OCR/Paddle
not accepted on this VM" and rerun the runtime smoke on an AVX-capable VM or a
MuMu-capable Windows host before claiming OCR/task-execution readiness.

Guest PowerShell scripts run by Windows PowerShell 5.1 should not rely on raw
UTF-8 Chinese string literals for executable names. Build names such as
`造笔.exe` with char codes (`$([char]0x9020)$([char]0x7b14).exe`) or save the
script with a BOM; otherwise `Start-Process` / `taskkill` can fail with "file not
found" after the install/update itself has succeeded.

The inverse applies to JSON marker files that Electron/Node reads directly,
such as `%APPDATA%\autoscriptor\install.json` and
`.autoscriptor\release_version.json`: write them as UTF-8 without BOM. In
Windows PowerShell 5.1, `Set-Content -Encoding UTF8` writes a BOM; use
`[System.IO.File]::WriteAllText($path, $json, [System.Text.UTF8Encoding]::new($false))`
instead so Node `JSON.parse` does not fail before launcher root detection.

## Update Package Acceptance

Use a clean VM snapshot and test the upgrade path, not only the final package:

1. Install the previous same-line version, for example `x.y.(z-1)`, using the full installer acceptance flow.
2. Launch the installed app and confirm the WebUI opens. Record this as a
   baseline launcher check before applying the update. If the baseline launcher
   cannot start WebUI under `VBoxManage guestcontrol`, keep testing the update
   layers, but do not attribute the launcher failure to the update package.
3. Open the WebUI release update page and choose `AutoScriptor_Update_x.y.z.zip`.
4. Confirm dry-run succeeds before applying. It must report the current version, target version, compatibility line, and protected user-data checks.
5. Apply the update.
6. Confirm the app restarts or can be relaunched.
7. Verify:
   - `.autoscriptor\release_version.json` under the install root reports `x.y.z`.
   - `%APPDATA%\autoscriptor\install.json` reports `version: x.y.z`.
   - `backend\autoscriptor-engine.exe` exists.
   - `data\config.json` remains valid JSON.
   - WebUI responds on `127.0.0.1:5000`.
   - User data such as accounts, custom tasks, and battle character data was not overwritten.

Local contract tests are still required, but they are not a substitute for VM upgrade acceptance:

```powershell
cd webapp
npm run test:installer
npm run test:release-update
```

When a release changes installer or update behavior, update this document and the scripts under `scripts/release/` together.

Keep same-line update reports split by layer:

- `Apply.Ok`, target version markers, and canary preservation prove the update
  zip could be applied to an existing install without overwriting protected
  user data.
- A direct `backend\autoscriptor-engine.exe --electron` WebUI probe proves the
  updated backend tree can run.
- A launcher probe proves only the Electron portable launcher path used by the
  probe. If both the pre-update baseline launcher and post-update launcher fail
  under `guestcontrol`, the result is "launcher path not VM-proven", not
  "update package broke the app".
- If the post-update launcher opens the old installer wizard and no
  `autoscriptor-engine.exe` appears, inspect whether the update package replaced
  the installed daily launcher `造笔.exe`. Same-line update packages that advance
  the recorded version must include the new launcher with `--include-file`.
- Before the post-update launcher probe, terminate the baseline launcher by the
  captured PID and by install-root path matching. Do not rely only on killing the
  Chinese image name `造笔.exe`; if that process remains, Electron's
  single-instance lock can make the post-update launcher probe fail without ever
  starting the backend.
- The real WebUI "choose zip and apply" path uses Electron IPC in an already
  running shell. It still needs manual UI validation or a dedicated hidden
  acceptance mode; backend direct probes alone do not prove the file-picker UI.

## What This Proves

- The release EXE starts on a clean Windows machine.
- The installation tree is complete.
- `install.json.dataRoot/config.json` is valid.
- Windows uninstall registration exists.
- The daily launcher exists.
- The local WebUI responds on `127.0.0.1:5000`.
- The same-line update package can upgrade an installed previous version without losing user data.

## MuMu-Capable Acceptance

The clean VirtualBox VM is useful for installer hygiene, but it may not prove
MuMu itself because nested virtualization can block Android emulators. Run this
extra check on a Windows machine where MuMu or MuMu12 is already installed and
can run normally:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\release\mumu_device_acceptance.ps1 `
  -InstallRoot D:\AutoScriptor `
  -ExercisePowerCycle `
  -ExerciseScreenshot
```

What this adds:

- Runs `backend\autoscriptor-engine.exe --runtime-import-smoke` from the
  installed release tree, catching packaged-only import gaps such as
  `MixControl`, `NemuIpc`, `box_grid`, editor routes, and digit extraction.
- Verifies port `5000` is free before launch, so the test cannot accidentally
  pass against a development WebUI.
- Starts the packaged WebUI and checks `/api/refresh`,
  `/api/runtime/snapshot`, `/api/overview`, and
  `/api/device/diagnostics`.
- By default, validates the device layer without requiring the game package.
  Add `-RequireApp` only when the game is installed and task execution should
  be validated too.
- With `-ExercisePowerCycle`, shuts down the configured MuMu instance first and
  proves AutoScriptor can start it again. With `-ExerciseScreenshot`, verifies
  NemuIpc screenshot capture.

Use `-ShutdownAfter` if the acceptance machine should leave MuMu closed after
the run. Logs and JSON reports are written to the `-OutDir` folder.

## Manual Items Still Needed

- MuMu real operation should be tested on a host/VM where MuMu can actually run. Nested virtualization may block MuMu inside VirtualBox.
- Full release-update UI automation still requires an additional hidden acceptance mode in the app. Without that, the update package step is intentionally manual in the VM.
