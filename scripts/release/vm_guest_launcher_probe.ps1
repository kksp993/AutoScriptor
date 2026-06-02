param(
  [string]$InstallRoot = "$env:USERPROFILE\Documents\AutoScriptorUpdateTest",
  [string]$OutPath = "\\VBOXSVR\release\logs\vm_update_100_to_101\launcher-after-update.json",
  [int]$TimeoutSeconds = 90,
  [string]$MarkerVersionOverride = ""
)

$ErrorActionPreference = "Stop"
$DailyLauncherName = "$([char]0x9020)$([char]0x7b14).exe"

function Wait-WebUi($Uri, [int]$TimeoutSeconds) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $attempts = 0
  $lastError = ""
  while ((Get-Date) -lt $deadline) {
    $attempts += 1
    try {
      $resp = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 5
      return [ordered]@{ Ok = $true; Attempts = $attempts; StatusCode = [int]$resp.StatusCode; LastError = $lastError }
    } catch {
      $lastError = $_.Exception.Message
      Start-Sleep -Seconds 2
    }
  }
  return [ordered]@{ Ok = $false; Attempts = $attempts; StatusCode = $null; LastError = $lastError }
}

function Read-Json($Path) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
  try { return Get-Content -Raw -Encoding UTF8 -LiteralPath $Path | ConvertFrom-Json } catch { return $null }
}

function Write-Json($Path, $Object) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
  $Object | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Get-RelevantProcesses() {
  $rows = @()
  try {
    $procs = Get-CimInstance Win32_Process -OperationTimeoutSec 10
    foreach ($p in $procs) {
      $name = [string]$p.Name
      $exe = [string]$p.ExecutablePath
      $cmd = [string]$p.CommandLine
      if (
        $name -eq $DailyLauncherName -or
        $name -eq "autoscriptor-engine.exe" -or
        ($exe -and $exe.IndexOf($InstallRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) -or
        ($cmd -and $cmd.IndexOf($InstallRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
      ) {
        $rows += [ordered]@{ ProcessId = [int]$p.ProcessId; Name = $name; ExecutablePath = $exe; CommandLine = $cmd }
      }
    }
  } catch {
    $rows += [ordered]@{ Error = $_.Exception.Message }
  }
  return $rows
}

$launcher = Join-Path $InstallRoot $DailyLauncherName
$markerPath = Join-Path $env:APPDATA "autoscriptor\install.json"
$releaseVersionPath = Join-Path $InstallRoot ".autoscriptor\release_version.json"

if ($MarkerVersionOverride) {
  $markerForUpdate = Read-Json $markerPath
  if ($markerForUpdate) {
    $markerForUpdate.version = $MarkerVersionOverride
    $markerForUpdate | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $markerPath -Encoding UTF8
  }
}

$result = [ordered]@{
  Time = (Get-Date).ToString("o")
  InstallRoot = $InstallRoot
  Launcher = $launcher
  LauncherExists = Test-Path -LiteralPath $launcher -PathType Leaf
  Marker = Read-Json $markerPath
  ReleaseVersion = Read-Json $releaseVersionPath
  StartProcessId = $null
  ProcessesBefore = @()
  ProcessesAfter = @()
  WebUi = $null
  Error = ""
}

try {
  foreach ($name in @("autoscriptor-engine.exe", $DailyLauncherName)) {
    try { & "$env:SystemRoot\System32\taskkill.exe" /IM $name /T /F 2>$null | Out-Null } catch {}
  }
  Start-Sleep -Seconds 2
  $result.ProcessesBefore = @(Get-RelevantProcesses)
  if (-not $result.LauncherExists) {
    throw "Missing launcher: $launcher"
  }
  $proc = Start-Process -FilePath $launcher -PassThru
  $result.StartProcessId = $proc.Id
  $result.WebUi = Wait-WebUi "http://127.0.0.1:5000" $TimeoutSeconds
  $result.ProcessesAfter = @(Get-RelevantProcesses)
} catch {
  $result.Error = $_.Exception.Message
  $result.ProcessesAfter = @(Get-RelevantProcesses)
} finally {
  Write-Json $OutPath $result
}

if (-not $result.WebUi -or -not $result.WebUi.Ok) {
  exit 1
}
