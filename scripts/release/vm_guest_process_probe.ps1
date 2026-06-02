param(
  [string]$OutPath = "\\VBOXSVR\release\logs\vm-process-probe.json"
)

$ErrorActionPreference = "Stop"

$items = Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -match "AutoScriptor|autoscriptor|powershell|node|electron|msedge" -or
    $_.CommandLine -match "AutoScriptor|autoscriptor|造笔|vm_guest_release_update|headless-install|release-update"
  } |
  Select-Object ProcessId, ParentProcessId, Name, CommandLine, CreationDate

$report = [ordered]@{
  Time = (Get-Date).ToString("o")
  Processes = @($items)
}

$dir = Split-Path -Parent $OutPath
if ($dir) {
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
}
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutPath -Encoding UTF8
$report
