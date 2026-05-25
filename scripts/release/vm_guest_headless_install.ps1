param(
  [string]$PackagePath = "\\VBOXSVR\release\AutoScriptor_Zao_Install_1.0.0.exe",
  [string]$LocalPackagePath = "$env:USERPROFILE\Downloads\AutoScriptor_Zao_Install_1.0.0.exe",
  [string]$InstallRoot = "$env:USERPROFILE\Documents\AutoScriptor",
  [string]$OutDir = "\\VBOXSVR\release\logs",
  [int]$InstallTimeoutSeconds = 900,
  [switch]$SkipMumuConfig
)

$ErrorActionPreference = "Stop"

function Write-Json($Path, $Object) {
  $Object | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Add-Error([ref]$Errors, [string]$Message) {
  $Errors.Value += $Message
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logRoot = Join-Path $OutDir "headless_$stamp"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

$errors = @()
$report = [ordered]@{
  Mode = "HeadlessInstall"
  Time = (Get-Date).ToString("o")
  Computer = $env:COMPUTERNAME
  User = $env:USERNAME
  PackagePath = $PackagePath
  LocalPackagePath = $LocalPackagePath
  InstallRoot = $InstallRoot
  LogRoot = $logRoot
  Checks = [ordered]@{
    InstallTimeoutSeconds = $InstallTimeoutSeconds
  }
  Errors = $errors
}

try {
  if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) {
    Add-Error ([ref]$errors) "Missing package: $PackagePath"
    throw "Package not found"
  }

  $sourceHash = Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256
  $report.Checks.PackageSha256 = $sourceHash.Hash

  $localDir = Split-Path -Parent $LocalPackagePath
  New-Item -ItemType Directory -Force -Path $localDir | Out-Null
  Copy-Item -LiteralPath $PackagePath -Destination $LocalPackagePath -Force

  $localHash = Get-FileHash -LiteralPath $LocalPackagePath -Algorithm SHA256
  $report.Checks.LocalPackageSha256 = $localHash.Hash
  if ($localHash.Hash -ne $sourceHash.Hash) {
    Add-Error ([ref]$errors) "Local package hash mismatch after copy"
  }

  $headlessReport = Join-Path $logRoot "headless-install.json"
  $args = @(
    "--headless-install",
    "--install-root=$InstallRoot",
    "--install-report=$headlessReport"
  )
  if ($SkipMumuConfig) {
    $args += "--skip-mumu-config"
  }

  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $proc = Start-Process -FilePath $LocalPackagePath -ArgumentList $args -PassThru
  $finished = $proc.WaitForExit([Math]::Max(1, $InstallTimeoutSeconds) * 1000)
  $sw.Stop()
  if (-not $finished) {
    $report.Checks.TimedOut = $true
    try {
      & "$env:SystemRoot\System32\taskkill.exe" /PID $proc.Id /T /F | Out-Null
    } catch {
      try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
    }
    Add-Error ([ref]$errors) "Headless installer timed out after ${InstallTimeoutSeconds}s"
  }

  $report.Checks.ExitCode = if ($finished) { $proc.ExitCode } else { $null }
  $report.Checks.ElapsedSeconds = [math]::Round($sw.Elapsed.TotalSeconds, 2)
  $report.Checks.HeadlessReportPath = $headlessReport
  if ($finished -and $proc.ExitCode -ne 0) {
    Add-Error ([ref]$errors) "Headless installer exit code: $($proc.ExitCode)"
  }

  if (Test-Path -LiteralPath $headlessReport -PathType Leaf) {
    $headless = Get-Content -LiteralPath $headlessReport -Raw -Encoding UTF8 | ConvertFrom-Json
    $report.Checks.HeadlessOk = [bool]$headless.ok
    $report.Checks.DryRunOk = [bool]($headless.dryRun -and $headless.dryRun.ok)
    $report.Checks.EventCount = @($headless.events).Count
    $report.Checks.LastEvents = @($headless.events | Select-Object -Last 12)
    if (-not $headless.ok) {
      Add-Error ([ref]$errors) "Headless installer report failed: $($headless.error)"
    }
  } else {
    Add-Error ([ref]$errors) "Headless installer did not write report: $headlessReport"
  }
} catch {
  if (-not $errors.Count) {
    Add-Error ([ref]$errors) $_.Exception.Message
  }
  $report.Checks.Exception = $_.Exception.Message
} finally {
  $report.Errors = $errors
  $report.Ok = ($errors.Count -eq 0)
  Write-Json (Join-Path $logRoot "report.json") $report
  $report
}

if ($errors.Count) { exit 1 }
