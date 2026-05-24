param(
  [ValidateSet("PreInstall", "PostInstall", "UninstallKeepData", "UninstallRemoveAll")]
  [string]$Mode = "PostInstall",
  [string]$PackagePath = "\\VBOXSVR\release\AutoScriptor_Zao_Install_1.0.0.exe",
  [string]$InstallRoot = "$env:LOCALAPPDATA\AutoScriptorReleaseTest",
  [string]$OutDir = "\\VBOXSVR\release\logs"
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

$logRoot = New-LogRoot
$errors = @()
$warnings = @()

$report = [ordered]@{
  Mode = $Mode
  Time = (Get-Date).ToString("o")
  Computer = $env:COMPUTERNAME
  User = $env:USERNAME
  PackagePath = $PackagePath
  InstallRoot = $InstallRoot
  Checks = [ordered]@{}
  Errors = $errors
  Warnings = $warnings
}

if ($Mode -eq "PreInstall") {
  Assert-File $PackagePath "release installer" ([ref]$errors)
  if (-not $errors.Count) {
    $hash = Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256
    $report.Checks.PackageSha256 = $hash.Hash
    Start-Process -FilePath $PackagePath
    $warnings += "Installer started. Choose install root: $InstallRoot, then rerun this script with -Mode PostInstall."
  }
} elseif ($Mode -eq "PostInstall") {
  Assert-Dir $InstallRoot "install root" ([ref]$errors)
  Assert-File (Join-Path $InstallRoot "backend\autoscriptor-engine.exe") "engine" ([ref]$errors)
  Assert-File (Join-Path $InstallRoot "data\config.json") "data/config.json" ([ref]$errors)
  Assert-File (Join-Path $InstallRoot "Uninstall.ps1") "Uninstall.ps1" ([ref]$errors)
  Assert-File (Join-Path $InstallRoot "卸载造笔.bat") "keep-data uninstall bat" ([ref]$errors)
  Assert-File (Join-Path $InstallRoot "彻底卸载造笔.bat") "remove-all uninstall bat" ([ref]$errors)
  Assert-File (Join-Path $InstallRoot "造笔.exe") "daily launcher" ([ref]$errors)

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

  $launcher = Join-Path $InstallRoot "造笔.exe"
  if (Test-Path -LiteralPath $launcher) {
    $proc = Start-Process -FilePath $launcher -PassThru
    Start-Sleep -Seconds 12
    try {
      $resp = Invoke-WebRequest -Uri "http://127.0.0.1:5000" -UseBasicParsing -TimeoutSec 5
      $report.Checks.WebUiHttpStatus = [int]$resp.StatusCode
    } catch {
      $errors += "WebUI did not respond on 127.0.0.1:5000: $($_.Exception.Message)"
    }
    Get-Process | Where-Object { $_.Path -like "$InstallRoot*" } | Select-Object Id,ProcessName,Path | Export-Csv -NoTypeInformation -Encoding UTF8 -LiteralPath (Join-Path $logRoot "processes.csv")
  }
} elseif ($Mode -eq "UninstallKeepData") {
  $bat = Join-Path $InstallRoot "卸载造笔.bat"
  Assert-File $bat "keep-data uninstall bat" ([ref]$errors)
  if (-not $errors.Count) {
    Start-Process -FilePath $bat -Wait
    Start-Sleep -Seconds 5
    $report.Checks.DataStillExists = Test-Path (Join-Path $InstallRoot "data")
    if (-not $report.Checks.DataStillExists) { $errors += "data should be preserved by keep-data uninstall" }
  }
} elseif ($Mode -eq "UninstallRemoveAll") {
  $bat = Join-Path $InstallRoot "彻底卸载造笔.bat"
  Assert-File $bat "remove-all uninstall bat" ([ref]$errors)
  if (-not $errors.Count) {
    Start-Process -FilePath $bat -Wait
    Start-Sleep -Seconds 10
    $report.Checks.InstallRootRemoved = -not (Test-Path $InstallRoot)
    if (-not $report.Checks.InstallRootRemoved) { $errors += "install root still exists after remove-all uninstall" }
  }
}

$report.Errors = $errors
$report.Warnings = $warnings
$report.Ok = ($errors.Count -eq 0)
Write-Json (Join-Path $logRoot "report.json") $report
$report
if ($errors.Count) { exit 1 }
