param(
  [Parameter(Mandatory = $true)]
  [string]$IsoPath,
  [string]$VmName = "AutoScriptor-Win-ReleaseLab",
  [string]$LabRoot = "C:\AutoScriptorReleaseLab",
  [int]$MemoryMB = 8192,
  [int]$CPUs = 4,
  [int]$DiskGB = 80,
  [string]$PackagePath = "D:\Projects\AutoScriptor\dist_electron\AutoScriptor_Zao_Install_1.0.0.exe",
  [switch]$Start
)

$ErrorActionPreference = "Stop"

function Require-File([string]$Path, [string]$Label) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "$Label not found: $Path"
  }
}

$vboxCmd = Get-Command VBoxManage -ErrorAction SilentlyContinue
$vboxPath = if ($vboxCmd) { $vboxCmd.Source } else { "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" }
if (-not (Test-Path -LiteralPath $vboxPath -PathType Leaf)) {
  throw "VBoxManage not found. Install Oracle VirtualBox first, then reopen PowerShell."
}

Require-File $IsoPath "Windows ISO"
Require-File $PackagePath "AutoScriptor release installer"

$lab = Resolve-Path -LiteralPath (New-Item -ItemType Directory -Force -Path $LabRoot)
$vmBase = Join-Path $lab "vms"
$shared = Join-Path $lab "shared"
$logs = Join-Path $lab "logs"
New-Item -ItemType Directory -Force -Path $vmBase, $shared, $logs | Out-Null

Copy-Item -LiteralPath $PackagePath -Destination (Join-Path $shared (Split-Path $PackagePath -Leaf)) -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "vm_guest_acceptance.ps1") -Destination (Join-Path $shared "vm_guest_acceptance.ps1") -Force

$existing = & $vboxPath list vms | Select-String -SimpleMatch "`"$VmName`""
if (-not $existing) {
  & $vboxPath createvm --name $VmName --basefolder $vmBase --ostype Windows11_64 --register | Out-Host
  & $vboxPath modifyvm $VmName --memory $MemoryMB --cpus $CPUs --vram 128 --graphicscontroller vboxsvga --firmware efi --tpm-type 2.0 --boot1 dvd --boot2 disk --nic1 nat --clipboard bidirectional --draganddrop bidirectional | Out-Host
  & $vboxPath modifynvram $VmName inituefivarstore | Out-Host
  & $vboxPath modifynvram $VmName enrollorclpk | Out-Host
  & $vboxPath modifynvram $VmName enrollmssignatures | Out-Host
  & $vboxPath modifynvram $VmName secureboot --enable | Out-Host
  & $vboxPath createmedium disk --filename (Join-Path $vmBase "$VmName\$VmName.vdi") --size ($DiskGB * 1024) --format VDI | Out-Host
  & $vboxPath storagectl $VmName --name "SATA" --add sata --controller IntelAhci --portcount 4 --bootable on | Out-Host
  & $vboxPath storageattach $VmName --storagectl "SATA" --port 0 --device 0 --type hdd --medium (Join-Path $vmBase "$VmName\$VmName.vdi") | Out-Host
  & $vboxPath storageattach $VmName --storagectl "SATA" --port 1 --device 0 --type dvddrive --medium (Resolve-Path -LiteralPath $IsoPath) | Out-Host
  & $vboxPath sharedfolder add $VmName --name release --hostpath $shared --automount | Out-Host
} else {
  Write-Host "VM already exists: $VmName"
}

Write-Host ""
Write-Host "Lab root: $LabRoot"
Write-Host "Shared folder: $shared"
Write-Host "Inside the VM, the shared folder is usually: \\VBOXSVR\release"
Write-Host ""
Write-Host "After Windows setup completes, install VirtualBox Guest Additions, then take a clean snapshot:"
Write-Host "  VBoxManage snapshot `"$VmName`" take clean-base"
Write-Host ""
Write-Host "Then run inside the VM:"
Write-Host "  powershell -ExecutionPolicy Bypass -File \\VBOXSVR\release\vm_guest_acceptance.ps1 -Mode PreInstall"
Write-Host "  powershell -ExecutionPolicy Bypass -File \\VBOXSVR\release\vm_guest_acceptance.ps1 -Mode PostInstall"

if ($Start) {
  & $vboxPath startvm $VmName --type gui | Out-Host
}
