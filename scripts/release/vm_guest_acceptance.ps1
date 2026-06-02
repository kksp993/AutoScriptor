param(
  [ValidateSet("PreInstall", "PostInstall", "UninstallKeepData", "UninstallRemoveAll")]
  [string]$Mode = "PostInstall",
  [string]$PackagePath = "\\VBOXSVR\release\AutoScriptor_Zao_Install_1.0.0.exe",
  [string]$LocalPackagePath = "$env:USERPROFILE\Downloads\AutoScriptor_Zao_Install_1.0.0.exe",
  [string]$InstallRoot = "$env:USERPROFILE\Documents\AutoScriptor",
  [string]$OutDir = "\\VBOXSVR\release\logs",
  [int]$WebUiTimeoutSeconds = 240
)

$ErrorActionPreference = "Stop"

function New-LogRoot {
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $root = Join-Path $OutDir "acceptance_$stamp"
  New-Item -ItemType Directory -Force -Path $root | Out-Null
  return $root
}

function Write-Json($Path, $Object) {
  $Object | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Assert-File($Path, $Name, [ref]$Errors) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    $Errors.Value += "Missing ${Name}: $Path"
  }
}

function Assert-Dir($Path, $Name, [ref]$Errors) {
  if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
    $Errors.Value += "Missing ${Name}: $Path"
  }
}

function Wait-Condition([scriptblock]$Condition, [int]$TimeoutSeconds = 60, [int]$PollSeconds = 2) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if (& $Condition) { return $true }
    Start-Sleep -Seconds $PollSeconds
  }
  return (& $Condition)
}

function Wait-WebUi($Uri, [int]$TimeoutSeconds = 90) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $attempts = 0
  $lastError = ""
  while ((Get-Date) -lt $deadline) {
    $attempts += 1
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
      $resp = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 5
      $sw.Stop()
      return [ordered]@{
        Ok = $true
        Attempts = $attempts
        StatusCode = [int]$resp.StatusCode
        ElapsedMs = [int]$sw.ElapsedMilliseconds
        LastError = $lastError
      }
    } catch {
      $sw.Stop()
      $lastError = $_.Exception.Message
      Start-Sleep -Seconds 2
    }
  }
  return [ordered]@{
    Ok = $false
    Attempts = $attempts
    StatusCode = $null
    ElapsedMs = $null
    LastError = $lastError
  }
}

function Export-Diagnostics($LogRoot, $InstallRoot) {
  try {
    $escapedRoot = [regex]::Escape($InstallRoot)
    Get-CimInstance Win32_Process -OperationTimeoutSec 10 |
      Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($InstallRoot, [System.StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and ($_.CommandLine -match $escapedRoot -or $_.CommandLine -match "autoscriptor|AutoScriptor|造笔"))
      } |
      Select-Object ProcessId, Name, ExecutablePath, CommandLine |
      Export-Csv -NoTypeInformation -Encoding UTF8 -LiteralPath (Join-Path $LogRoot "processes.csv")
  } catch {
    $_ | Out-File -Encoding UTF8 -Append -LiteralPath (Join-Path $LogRoot "diagnostics-error.log")
  }

  try {
    $userData = Join-Path $env:APPDATA "autoscriptor"
    if (Test-Path -LiteralPath $userData) {
      Get-ChildItem -LiteralPath $userData -Force |
        Select-Object Name, Length, LastWriteTime, FullName |
        Export-Csv -NoTypeInformation -Encoding UTF8 -LiteralPath (Join-Path $LogRoot "userdata-files.csv")
      $marker = Join-Path $userData "install.json"
      if (Test-Path -LiteralPath $marker) {
        Copy-Item -LiteralPath $marker -Destination (Join-Path $LogRoot "install.json") -Force
      }
    }
  } catch {
    $_ | Out-File -Encoding UTF8 -Append -LiteralPath (Join-Path $LogRoot "diagnostics-error.log")
  }
}

$DailyLauncherName = "$([char]0x9020)$([char]0x7b14).exe"
$KeepDataUninstallName = "$([char]0x5378)$([char]0x8f7d)$([char]0x9020)$([char]0x7b14).bat"
$RemoveAllUninstallName = "$([char]0x5f7b)$([char]0x5e95)$([char]0x5378)$([char]0x8f7d)$([char]0x9020)$([char]0x7b14).bat"

$logRoot = New-LogRoot
$errors = @()
$warnings = @()

$report = [ordered]@{
  Mode = $Mode
  Time = (Get-Date).ToString("o")
  Computer = $env:COMPUTERNAME
  User = $env:USERNAME
  PackagePath = $PackagePath
  LocalPackagePath = $LocalPackagePath
  InstallRoot = $InstallRoot
  Checks = [ordered]@{
    WebUiTimeoutSeconds = $WebUiTimeoutSeconds
  }
  Errors = $errors
  Warnings = $warnings
}

if ($Mode -eq "PreInstall") {
  Assert-File $PackagePath "release installer" ([ref]$errors)
  if (-not $errors.Count) {
    $hash = Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256
    $report.Checks.PackageSha256 = $hash.Hash
    $localDir = Split-Path -Parent $LocalPackagePath
    New-Item -ItemType Directory -Force -Path $localDir | Out-Null
    Copy-Item -LiteralPath $PackagePath -Destination $LocalPackagePath -Force
    $localHash = Get-FileHash -LiteralPath $LocalPackagePath -Algorithm SHA256
    $report.Checks.LocalPackageSha256 = $localHash.Hash
    if ($localHash.Hash -ne $hash.Hash) {
      $errors += "Local package hash mismatch after copy: $LocalPackagePath"
    } else {
      Start-Process -FilePath $LocalPackagePath
      $warnings += "Installer copied locally and started. Choose install root: $InstallRoot, then rerun this script with -Mode PostInstall."
    }
  }
} elseif ($Mode -eq "PostInstall") {
  Assert-Dir $InstallRoot "install root" ([ref]$errors)
  Assert-File (Join-Path $InstallRoot "backend\autoscriptor-engine.exe") "engine" ([ref]$errors)
  Assert-File (Join-Path $InstallRoot "backend\vcomp140.dll") "VC OpenMP runtime" ([ref]$errors)
  Assert-File (Join-Path $InstallRoot "backend\paddle\libs\mkldnn.dll") "Paddle MKLDNN runtime" ([ref]$errors)
  Assert-File (Join-Path $InstallRoot "data\config.json") "data/config.json" ([ref]$errors)
  Assert-File (Join-Path $InstallRoot "Uninstall.ps1") "Uninstall.ps1" ([ref]$errors)
  Assert-File (Join-Path $InstallRoot $KeepDataUninstallName) "keep-data uninstall bat" ([ref]$errors)
  Assert-File (Join-Path $InstallRoot $RemoveAllUninstallName) "remove-all uninstall bat" ([ref]$errors)
  Assert-File (Join-Path $InstallRoot $DailyLauncherName) "daily launcher" ([ref]$errors)

  $cfgPath = Join-Path $InstallRoot "data\config.json"
  if (Test-Path -LiteralPath $cfgPath) {
    try {
      $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
      $report.Checks.ConfigAppName = $cfg.app.name
      if ($cfg.app.name -ne "ZmxyOL") { $errors += "Unexpected app.name: $($cfg.app.name)" }
    } catch {
      $errors += "config.json is not valid JSON: $($_.Exception.Message)"
    }
  }

  $uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoScriptorZao"
  $report.Checks.UninstallRegistryExists = Test-Path $uninstallKey
  if (-not $report.Checks.UninstallRegistryExists) {
    $errors += "Windows uninstall registry key missing: $uninstallKey"
  }

  $launcher = Join-Path $InstallRoot $DailyLauncherName
  if (Test-Path -LiteralPath $launcher) {
    $proc = Start-Process -FilePath $launcher -PassThru
    $report.Checks.LauncherProcessId = $proc.Id
    $web = Wait-WebUi "http://127.0.0.1:5000" $WebUiTimeoutSeconds
    $report.Checks.WebUi = $web
    if (-not $web.Ok) {
      $errors += "WebUI did not respond on 127.0.0.1:5000 within ${WebUiTimeoutSeconds}s: $($web.LastError)"
    }
    Export-Diagnostics $logRoot $InstallRoot
  }
} elseif ($Mode -eq "UninstallKeepData") {
  $bat = Join-Path $InstallRoot $KeepDataUninstallName
  Assert-File $bat "keep-data uninstall bat" ([ref]$errors)
  if (-not $errors.Count) {
    Start-Process -FilePath $bat -Wait
    $report.Checks.AppFilesRemoved = Wait-Condition { -not (Test-Path (Join-Path $InstallRoot "backend")) } 45 2
    $report.Checks.DataStillExists = Test-Path (Join-Path $InstallRoot "data")
    $report.Checks.UninstallRegistryRemoved = -not (Test-Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoScriptorZao")
    if (-not $report.Checks.AppFilesRemoved) { $errors += "backend should be removed by keep-data uninstall" }
    if (-not $report.Checks.DataStillExists) { $errors += "data should be preserved by keep-data uninstall" }
    if (-not $report.Checks.UninstallRegistryRemoved) { $errors += "uninstall registry should be removed by keep-data uninstall" }
    Export-Diagnostics $logRoot $InstallRoot
  }
} elseif ($Mode -eq "UninstallRemoveAll") {
  $bat = Join-Path $InstallRoot $RemoveAllUninstallName
  Assert-File $bat "remove-all uninstall bat" ([ref]$errors)
  if (-not $errors.Count) {
    Start-Process -FilePath $bat -Wait
    $null = Wait-Condition { -not (Test-Path $InstallRoot) } 60 2
    $report.Checks.InstallRootRemoved = -not (Test-Path $InstallRoot)
    if (-not $report.Checks.InstallRootRemoved) { $errors += "install root still exists after remove-all uninstall" }
    Export-Diagnostics $logRoot $InstallRoot
  }
}

$report.Errors = $errors
$report.Warnings = $warnings
$report.Ok = ($errors.Count -eq 0)
Write-Json (Join-Path $logRoot "report.json") $report
$report
if ($errors.Count) { exit 1 }
