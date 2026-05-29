# Release VM Acceptance

This document is the Windows VM lab plan for validating release artifacts. A release is not accepted until both the full installer and the same-line update package have been checked when both are produced.

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

## Update Package Acceptance

Use a clean VM snapshot and test the upgrade path, not only the final package:

1. Install the previous same-line version, for example `x.y.(z-1)`, using the full installer acceptance flow.
2. Launch the installed app and confirm the WebUI opens.
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

## What This Proves

- The release EXE starts on a clean Windows machine.
- The installation tree is complete.
- `data/config.json` is valid.
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
