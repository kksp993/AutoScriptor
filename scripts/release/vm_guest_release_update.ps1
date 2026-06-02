param(
  [string]$OldPackagePath = "\\VBOXSVR\release\AutoScriptor_Zao_Install_1.0.0.exe",
  [string]$UpdatePackagePath = "\\VBOXSVR\release\AutoScriptor_Update_1.0.1.zip",
  [string]$InstallRoot = "$env:USERPROFILE\Documents\AutoScriptorUpdateTest",
  [string]$OutDir = "\\VBOXSVR\release\logs",
  [int]$InstallTimeoutSeconds = 900,
  [int]$WebUiTimeoutSeconds = 180,
  [switch]$SkipMumuConfig
)

$ErrorActionPreference = "Stop"
$DailyLauncherName = "$([char]0x9020)$([char]0x7b14).exe"

function Write-Json($Path, $Object) {
  $Object | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Add-Error([ref]$Errors, [string]$Message) {
  $Errors.Value += $Message
}

function Assert-SafeInstallRoot([string]$Path) {
  $resolved = [System.IO.Path]::GetFullPath($Path)
  $documents = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($env:USERPROFILE, "Documents"))
  if (-not $resolved.StartsWith($documents, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "InstallRoot must stay under the guest Documents directory for this destructive VM test: $resolved"
  }
}

function Stop-AutoScriptorProcesses() {
  foreach ($name in @($script:DailyLauncherName, "autoscriptor-engine.exe")) {
    try { & "$env:SystemRoot\System32\taskkill.exe" /IM $name /T /F 2>$null | Out-Null } catch {}
  }
}

function Wait-WebUi($Uri, [int]$TimeoutSeconds) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $attempts = 0
  $lastError = ""
  while ((Get-Date) -lt $deadline) {
    $attempts += 1
    try {
      $resp = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 5
      return [ordered]@{
        Ok = $true
        Attempts = $attempts
        StatusCode = [int]$resp.StatusCode
        LastError = $lastError
      }
    } catch {
      $lastError = $_.Exception.Message
      Start-Sleep -Seconds 2
    }
  }
  return [ordered]@{
    Ok = $false
    Attempts = $attempts
    StatusCode = $null
    LastError = $lastError
  }
}

function Start-BackendAndWait-WebUi([string]$Root, [int]$TimeoutSeconds) {
  $engine = Join-Path $Root "backend\autoscriptor-engine.exe"
  $result = [ordered]@{
    Engine = $engine
    EngineExists = Test-Path -LiteralPath $engine -PathType Leaf
    ProcessId = $null
    WebUi = $null
    Error = ""
  }
  if (-not $result.EngineExists) {
    $result.Error = "backend autoscriptor-engine.exe is missing"
    $result.WebUi = [ordered]@{ Ok = $false; Attempts = 0; StatusCode = $null; LastError = $result.Error }
    return $result
  }
  try {
    $proc = Start-Process -FilePath $engine -ArgumentList @("--electron") -WorkingDirectory (Split-Path -Parent $engine) -PassThru
    $result.ProcessId = $proc.Id
    $result.WebUi = Wait-WebUi "http://127.0.0.1:5000" $TimeoutSeconds
  } catch {
    $result.Error = $_.Exception.Message
    $result.WebUi = [ordered]@{ Ok = $false; Attempts = 0; StatusCode = $null; LastError = $result.Error }
  }
  return $result
}

function Get-ZipEntryMap($Zip) {
  $map = @{}
  foreach ($entry in $Zip.Entries) {
    if (-not $entry.FullName.EndsWith("/")) {
      $map[$entry.FullName.Replace("\", "/").TrimStart("/")] = $entry
    }
  }
  return $map
}

function Read-ZipText($Entry) {
  $stream = $Entry.Open()
  try {
    $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
    try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
  } finally {
    $stream.Dispose()
  }
}

function Normalize-UpdatePath([string]$Path) {
  $n = ($Path -replace "\\", "/").Trim().TrimStart("/")
  if (-not $n -or $n.Contains("..") -or $n.Contains([char]0)) {
    throw "Illegal update path: $Path"
  }
  if ([System.IO.Path]::IsPathRooted($n) -or $n -match "^[A-Za-z]:/") {
    throw "Illegal rooted update path: $Path"
  }
  return $n
}

function Test-ProtectedUpdatePath([string]$Path) {
  $n = (Normalize-UpdatePath $Path).ToLowerInvariant()
  return (
    $n -eq "data/config.json" -or
    $n -eq "config.json" -or
    $n.StartsWith("data/accounts/") -or
    $n.StartsWith("data/custom_task/") -or
    $n.StartsWith("data/battle_character/") -or
    $n.StartsWith("data/logs/") -or
    $n.StartsWith("accounts/") -or
    $n.StartsWith("custom_task/") -or
    $n.StartsWith("battle_character/") -or
    $n.StartsWith("logs/") -or
    $n.StartsWith(".autoscriptor/")
  )
}

function Resolve-UnderRoot([string]$Root, [string]$RelPath) {
  $rootAbs = [System.IO.Path]::GetFullPath($Root)
  $target = [System.IO.Path]::GetFullPath((Join-Path $rootAbs (Normalize-UpdatePath $RelPath)))
  if (-not $target.StartsWith($rootAbs, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Update path escapes install root: $RelPath"
  }
  return $target
}

function Apply-ReleaseUpdateZip([string]$PackagePath, [string]$Root, [string]$UserDataPath, [scriptblock]$Send) {
  Add-Type -AssemblyName System.IO.Compression.FileSystem

  $zip = [System.IO.Compression.ZipFile]::OpenRead($PackagePath)
  $staging = Join-Path $Root (".update.staging." + (Get-Date -Format "yyyyMMddHHmmss") + "." + $PID)
  $backup = Join-Path $Root (".update-backup." + (Get-Date -Format "yyyyMMddHHmmss") + "." + $PID)
  $applied = @()
  try {
    $map = Get-ZipEntryMap $zip
    if (-not $map.ContainsKey("update_manifest.json")) {
      throw "Update package missing update_manifest.json"
    }
    $manifest = Read-ZipText $map["update_manifest.json"] | ConvertFrom-Json
    if ($manifest.format -ne "autoscriptor_update_v1") {
      throw "Unsupported update format: $($manifest.format)"
    }
    if ($manifest.compat_line -ne "1.0" -or $manifest.target_version -ne "1.0.1") {
      throw "Unexpected update target: compat=$($manifest.compat_line) target=$($manifest.target_version)"
    }

    New-Item -ItemType Directory -Force -Path $staging, $backup | Out-Null
    $replace = @($manifest.replace)
    $idx = 0
    foreach ($op in $replace) {
      $idx += 1
      $rel = Normalize-UpdatePath $op.path
      if (Test-ProtectedUpdatePath $rel) {
        throw "Update package touches protected user data path: $rel"
      }
      $entryName = if ($op.entry) { Normalize-UpdatePath $op.entry } else { $rel }
      if (-not $map.ContainsKey($entryName)) {
        throw "Update payload missing: $entryName"
      }
      $target = Resolve-UnderRoot $Root $rel
      $staged = Resolve-UnderRoot $staging $entryName
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $staged) | Out-Null
      [System.IO.Compression.ZipFileExtensions]::ExtractToFile($map[$entryName], $staged, $true)
      $sha = (Get-FileHash -LiteralPath $staged -Algorithm SHA256).Hash.ToLowerInvariant()
      if ($sha -ne ([string]$op.sha256).ToLowerInvariant()) {
        throw "Staged SHA mismatch for ${rel}: $sha"
      }

      $item = [ordered]@{ Target = $target; Backup = $null }
      if (Test-Path -LiteralPath $target -PathType Leaf) {
        $backupPath = Resolve-UnderRoot $backup $rel
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backupPath) | Out-Null
        Move-Item -LiteralPath $target -Destination $backupPath -Force
        $item.Backup = $backupPath
      }
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
      Move-Item -LiteralPath $staged -Destination $target -Force
      $got = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
      if ($got -ne ([string]$op.sha256).ToLowerInvariant()) {
        throw "Target SHA mismatch for ${rel}: $got"
      }
      $applied += $item
      & $Send ([ordered]@{ type = "progress"; percent = [Math]::Min(90, 10 + [Math]::Floor(80 * $idx / [Math]::Max(1, $replace.Count))); message = "updated $idx/$($replace.Count) $rel" })
    }

    $versionDir = Join-Path $Root ".autoscriptor"
    New-Item -ItemType Directory -Force -Path $versionDir | Out-Null
    Write-Json (Join-Path $versionDir "release_version.json") ([ordered]@{
      version = [string]$manifest.target_version
      updated_at = (Get-Date).ToString("o")
    })
    $markerPath = Join-Path $UserDataPath "install.json"
    $marker = @{}
    if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
      $marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    $marker.installRoot = $Root
    $marker.version = [string]$manifest.target_version
    New-Item -ItemType Directory -Force -Path $UserDataPath | Out-Null
    Write-Json $markerPath $marker

    Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
    return [ordered]@{
      Ok = $true
      TargetVersion = [string]$manifest.target_version
      ReplaceCount = $replace.Count
      Paths = @($replace | ForEach-Object { Normalize-UpdatePath $_.path })
    }
  } catch {
    foreach ($item in [array]::Reverse($applied)) {
      try {
        if (Test-Path -LiteralPath $item.Target) {
          Remove-Item -LiteralPath $item.Target -Force -Recurse -ErrorAction SilentlyContinue
        }
        if ($item.Backup -and (Test-Path -LiteralPath $item.Backup)) {
          New-Item -ItemType Directory -Force -Path (Split-Path -Parent $item.Target) | Out-Null
          Move-Item -LiteralPath $item.Backup -Destination $item.Target -Force
        }
      } catch {}
    }
    throw
  } finally {
    try { $zip.Dispose() } catch {}
    Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
  }
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logRoot = Join-Path $OutDir "release_update_$stamp"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

$errors = @()
$events = @()
$report = [ordered]@{
  Mode = "ReleaseUpdate"
  Time = (Get-Date).ToString("o")
  Computer = $env:COMPUTERNAME
  User = $env:USERNAME
  OldPackagePath = $OldPackagePath
  UpdatePackagePath = $UpdatePackagePath
  InstallRoot = $InstallRoot
  LogRoot = $logRoot
  Checks = [ordered]@{}
  Events = $events
  Errors = $errors
}

try {
  Assert-SafeInstallRoot $InstallRoot
  if (-not (Test-Path -LiteralPath $OldPackagePath -PathType Leaf)) { throw "Missing old package: $OldPackagePath" }
  if (-not (Test-Path -LiteralPath $UpdatePackagePath -PathType Leaf)) { throw "Missing update package: $UpdatePackagePath" }

  Stop-AutoScriptorProcesses
  if (Test-Path -LiteralPath $InstallRoot) {
    Remove-Item -LiteralPath $InstallRoot -Recurse -Force
  }
  $userDataPath = Join-Path $env:APPDATA "autoscriptor"
  if (Test-Path -LiteralPath (Join-Path $userDataPath "install.json")) {
    Remove-Item -LiteralPath (Join-Path $userDataPath "install.json") -Force
  }

  $localDir = Join-Path $env:USERPROFILE "Downloads"
  New-Item -ItemType Directory -Force -Path $localDir | Out-Null
  $localOld = Join-Path $localDir "AutoScriptor_Zao_Install_1.0.0.exe"
  $localUpdate = Join-Path $localDir "AutoScriptor_Update_1.0.1.zip"
  Copy-Item -LiteralPath $OldPackagePath -Destination $localOld -Force
  Copy-Item -LiteralPath $UpdatePackagePath -Destination $localUpdate -Force
  $report.Checks.OldPackageSha256 = (Get-FileHash -LiteralPath $localOld -Algorithm SHA256).Hash
  $report.Checks.UpdatePackageSha256 = (Get-FileHash -LiteralPath $localUpdate -Algorithm SHA256).Hash

  $headlessReport = Join-Path $logRoot "headless-100-install.json"
  $args = @("--headless-install", "--install-root=$InstallRoot", "--install-report=$headlessReport")
  if ($SkipMumuConfig) { $args += "--skip-mumu-config" }
  $proc = Start-Process -FilePath $localOld -ArgumentList $args -PassThru
  $finished = $proc.WaitForExit([Math]::Max(1, $InstallTimeoutSeconds) * 1000)
  if (-not $finished) {
    try { & "$env:SystemRoot\System32\taskkill.exe" /PID $proc.Id /T /F | Out-Null } catch {}
    throw "1.0.0 headless install timed out"
  }
  $report.Checks.Headless100ExitCode = $proc.ExitCode
  if ($proc.ExitCode -ne 0) { throw "1.0.0 headless install exit code: $($proc.ExitCode)" }
  $headless = Get-Content -LiteralPath $headlessReport -Raw -Encoding UTF8 | ConvertFrom-Json
  $report.Checks.Headless100Ok = [bool]$headless.ok
  if (-not $headless.ok) { throw "1.0.0 headless install report failed: $($headless.error)" }

  $baselineLauncher = Join-Path $InstallRoot $DailyLauncherName
  $baselineLaunch = Start-Process -FilePath $baselineLauncher -PassThru
  $report.Checks.Baseline100LauncherProcessId = $baselineLaunch.Id
  $baselineWeb = Wait-WebUi "http://127.0.0.1:5000" $WebUiTimeoutSeconds
  $report.Checks.Baseline100WebUi = $baselineWeb
  if (-not $baselineWeb.Ok) {
    Add-Error ([ref]$errors) "Baseline 1.0.0 launcher WebUI did not respond: $($baselineWeb.LastError)"
  }
  Stop-AutoScriptorProcesses

  $accountsDir = Join-Path $InstallRoot "data\accounts"
  $customDir = Join-Path $InstallRoot "data\custom_task"
  $battleDir = Join-Path $InstallRoot "data\battle_character"
  New-Item -ItemType Directory -Force -Path $accountsDir, $customDir, $battleDir | Out-Null
  Set-Content -LiteralPath (Join-Path $accountsDir "default.json") -Encoding UTF8 -Value '{"vm_update_canary":"account-kept"}'
  Set-Content -LiteralPath (Join-Path $customDir "vm_update_canary.py") -Encoding UTF8 -Value "# vm custom task canary"
  Set-Content -LiteralPath (Join-Path $battleDir "vm_update_canary.py") -Encoding UTF8 -Value "# vm battle character canary"
  $report.Checks.CanariesWritten = $true

  Stop-AutoScriptorProcesses
  $apply = Apply-ReleaseUpdateZip $localUpdate $InstallRoot $userDataPath {
    param($event)
    $script:events += $event
  }
  $report.Checks.Apply = $apply

  $marker = Get-Content -LiteralPath (Join-Path $userDataPath "install.json") -Raw -Encoding UTF8 | ConvertFrom-Json
  $versionFile = Get-Content -LiteralPath (Join-Path $InstallRoot ".autoscriptor\release_version.json") -Raw -Encoding UTF8 | ConvertFrom-Json
  $report.Checks.InstallMarkerVersion = $marker.version
  $report.Checks.ReleaseVersion = $versionFile.version
  if ($marker.version -ne "1.0.1") { Add-Error ([ref]$errors) "install.json version is not 1.0.1: $($marker.version)" }
  if ($versionFile.version -ne "1.0.1") { Add-Error ([ref]$errors) "release_version.json version is not 1.0.1: $($versionFile.version)" }

  $report.Checks.AccountCanaryPreserved = (Get-Content -LiteralPath (Join-Path $accountsDir "default.json") -Raw -Encoding UTF8).Contains("account-kept")
  $report.Checks.CustomTaskCanaryPreserved = Test-Path -LiteralPath (Join-Path $customDir "vm_update_canary.py")
  $report.Checks.BattleCanaryPreserved = Test-Path -LiteralPath (Join-Path $battleDir "vm_update_canary.py")
  foreach ($name in @("AccountCanaryPreserved", "CustomTaskCanaryPreserved", "BattleCanaryPreserved")) {
    if (-not $report.Checks[$name]) { Add-Error ([ref]$errors) "$name failed" }
  }

  $cfg = Get-Content -LiteralPath (Join-Path $InstallRoot "data\config.json") -Raw -Encoding UTF8 | ConvertFrom-Json
  $report.Checks.NewsAccount = $cfg.news.account
  $report.Checks.NewsPasswordPlaintext = $cfg.news.password
  if ($cfg.news.account -ne "85rwm3janyyc" -or $cfg.news.password -ne "123456") {
    Add-Error ([ref]$errors) "public news credentials were not preserved in plaintext"
  }

  $launcher = Join-Path $InstallRoot $DailyLauncherName
  $launch = Start-Process -FilePath $launcher -PassThru
  $report.Checks.LauncherProcessId = $launch.Id
  $web = Wait-WebUi "http://127.0.0.1:5000" $WebUiTimeoutSeconds
  $report.Checks.WebUi = $web
  if (-not $web.Ok) {
    Add-Error ([ref]$errors) "WebUI did not respond after update: $($web.LastError)"
  }

  Stop-AutoScriptorProcesses
  $direct = Start-BackendAndWait-WebUi $InstallRoot $WebUiTimeoutSeconds
  $report.Checks.BackendDirect = $direct
  if (-not $direct.WebUi.Ok) {
    Add-Error ([ref]$errors) "Direct backend WebUI did not respond after update: $($direct.WebUi.LastError)"
  }
} catch {
  if (-not $errors.Count) { Add-Error ([ref]$errors) $_.Exception.Message }
  $report.Checks.Exception = $_.Exception.Message
} finally {
  $report.Events = $events
  $report.Errors = $errors
  $report.Ok = ($errors.Count -eq 0)
  Write-Json (Join-Path $logRoot "report.json") $report
  $report
}

if ($errors.Count) { exit 1 }
