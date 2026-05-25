# Release VM Acceptance

This document is the minimal Windows VM lab plan for validating a release installer.

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

## Guest Acceptance

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

## What This Proves

- The release EXE starts on a clean Windows machine.
- The installation tree is complete.
- `data/config.json` is valid.
- Windows uninstall registration exists.
- The daily launcher exists.
- The local WebUI responds on `127.0.0.1:5000`.

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
- Full UI automation requires an additional hidden acceptance mode in the app. Without that, the installer UI step is intentionally manual.
