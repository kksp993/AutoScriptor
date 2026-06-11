param(
  [string]$InstallRoot = "$env:USERPROFILE\Documents\AutoScriptorUpdateTest",
  [string]$NewLauncherPath = "\\VBOXSVR\release\AutoScriptor_Zao_Install_1.0.2.exe"
)

$ErrorActionPreference = "Stop"
$DailyLauncherName = "$([char]0x9020)$([char]0x7b14).exe"

foreach ($name in @("autoscriptor-engine.exe", $DailyLauncherName)) {
  try { & "$env:SystemRoot\System32\taskkill.exe" /IM $name /T /F 2>$null | Out-Null } catch {}
}

$dest = Join-Path $InstallRoot $DailyLauncherName
if (-not (Test-Path -LiteralPath $NewLauncherPath -PathType Leaf)) {
  throw "Missing new launcher: $NewLauncherPath"
}
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
Copy-Item -LiteralPath $NewLauncherPath -Destination $dest -Force
Get-Item -LiteralPath $dest | Select-Object FullName, Length, LastWriteTime
