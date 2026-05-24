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

## Manual Items Still Needed

- MuMu real operation should be tested on a host/VM where MuMu can actually run. Nested virtualization may block MuMu inside VirtualBox.
- Full UI automation requires an additional hidden acceptance mode in the app. Without that, the installer UI step is intentionally manual.
