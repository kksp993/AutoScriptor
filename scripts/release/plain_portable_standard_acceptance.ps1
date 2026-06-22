param(
  [string]$PortableZip = "dist_plain_portable\AutoScriptor_Zao_Plain_Portable_1.0.2.zip",
  [string]$UpdateZip = "dist_plain_portable\AutoScriptor_Update_1.0.2.zip",
  [string]$WorkRoot = "$env:LOCALAPPDATA\AutoScriptorPlainStandardTest",
  [string]$OutDir = "dist_plain_portable\standard_acceptance_logs",
  [int]$WindowTimeoutSeconds = 10,
  [int]$WebUiTimeoutSeconds = 90,
  [switch]$KeepTestUserData,
  [switch]$RequireDeviceDiagnostics
)

$ErrorActionPreference = "Stop"
$LauncherName = "$([char]0x9020)$([char]0x7b14).exe"

function Resolve-ProjectPath([string]$PathValue) {
  if ([System.IO.Path]::IsPathRooted($PathValue)) { return $PathValue }
  return (Join-Path (Get-Location).Path $PathValue)
}

function Write-JsonNoBom($Path, $Object) {
  $json = $Object | ConvertTo-Json -Depth 80
  [System.IO.File]::WriteAllText($Path, $json, [System.Text.UTF8Encoding]::new($false))
}

function Add-Err([ref]$Errors, [string]$Message) {
  $Errors.Value += $Message
}

function Stop-TestProcesses([string]$Root) {
  try {
    $launcherProcessName = [System.IO.Path]::GetFileNameWithoutExtension($LauncherName)
    Get-Process -Name $launcherProcessName, "autoscriptor-engine" -ErrorAction SilentlyContinue |
      Where-Object { $_.Path -and $_.Path.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase) } |
      Stop-Process -Force -ErrorAction SilentlyContinue
  } catch {}
  if ($IsWindows -or $env:OS -eq "Windows_NT") {
    try {
      $matched = @(Get-CimInstance Win32_Process -OperationTimeoutSec 10 |
        Where-Object {
          ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)) -or
          ($_.CommandLine -and $_.CommandLine.IndexOf($Root, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
        })
      foreach ($item in $matched) {
        try { Stop-Process -Id $item.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
        try { & "$env:SystemRoot\System32\taskkill.exe" /PID $item.ProcessId /T /F 2>$null | Out-Null } catch {}
      }
    } catch {}
  }
  $deadline = (Get-Date).AddSeconds(8)
  while ((Get-Date) -lt $deadline) {
    $alive = @()
    try {
      $alive = @(Get-CimInstance Win32_Process -OperationTimeoutSec 10 |
        Where-Object {
          ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)) -or
          ($_.CommandLine -and $_.CommandLine.IndexOf($Root, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
        })
    } catch {}
    if (-not $alive.Count) { break }
    Start-Sleep -Milliseconds 500
  }
  Start-Sleep -Seconds 3
}

function Wait-WebUi([int]$TimeoutSeconds) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $last = ""
  while ((Get-Date) -lt $deadline) {
    try {
      $resp = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:5000/api/refresh" -TimeoutSec 3
      if ([int]$resp.StatusCode -eq 200) {
        $sw.Stop()
        return @{ Ok = $true; ElapsedMs = [int]$sw.ElapsedMilliseconds; LastError = "" }
      }
    } catch {
      $last = $_.Exception.Message
    }
    Start-Sleep -Milliseconds 500
  }
  $sw.Stop()
  return @{ Ok = $false; ElapsedMs = [int]$sw.ElapsedMilliseconds; LastError = $last }
}

function Invoke-Api($Method, $Path, $Body = $null) {
  $uri = "http://127.0.0.1:5000/api$Path"
  $args = @{
    Uri = $uri
    Method = $Method
    UseBasicParsing = $true
    TimeoutSec = 30
    WebSession = $script:Session
  }
  if ($null -ne $Body) {
    $args.ContentType = "application/json; charset=utf-8"
    $json = ($Body | ConvertTo-Json -Depth 80)
    $args.Body = [System.Text.Encoding]::UTF8.GetBytes($json)
  }
  $resp = Invoke-WebRequest @args
  if ($resp.Content) { return ($resp.Content | ConvertFrom-Json) }
  return $null
}

function Get-ZipEntries([string]$ZipPath) {
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
  try {
    return @($zip.Entries | ForEach-Object { $_.FullName.Replace("\", "/") })
  } finally {
    $zip.Dispose()
  }
}

function Get-Props($Object) {
  if ($null -eq $Object) { return @() }
  return @($Object.PSObject.Properties)
}

function Count-Roles($AccountJson) {
  $count = 0
  foreach ($serverProp in Get-Props $AccountJson.characters) {
    $count += @(Get-Props $serverProp.Value).Count
  }
  return $count
}

Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue

$PortableZip = Resolve-ProjectPath $PortableZip
$UpdateZip = Resolve-ProjectPath $UpdateZip
$WorkRoot = Resolve-ProjectPath $WorkRoot
$OutDir = Resolve-ProjectPath $OutDir
$appRoot = Join-Path $WorkRoot "app"
$userDataRoot = Join-Path $env:APPDATA "autoscriptor"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logRoot = Join-Path $OutDir "plain_standard_$stamp"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$userDataBackup = Join-Path $logRoot "autoscriptor-userData-backup"

$errors = @()
$warnings = @()
$checks = [ordered]@{}
$report = [ordered]@{
  Mode = "PlainPortableStandardAcceptance"
  Time = (Get-Date).ToString("o")
  Computer = $env:COMPUTERNAME
  User = $env:USERNAME
  PortableZip = $PortableZip
  UpdateZip = $UpdateZip
  WorkRoot = $WorkRoot
  UserDataRoot = $userDataRoot
  LogRoot = $logRoot
  Checks = $checks
  Errors = $errors
  Warnings = $warnings
}

try {
  if (-not (Test-Path -LiteralPath $PortableZip -PathType Leaf)) { throw "Missing portable zip: $PortableZip" }
  if (-not (Test-Path -LiteralPath $UpdateZip -PathType Leaf)) { throw "Missing update zip: $UpdateZip" }

  $checks.Artifacts = @{
    PortableSize = (Get-Item -LiteralPath $PortableZip).Length
    PortableSha256 = (Get-FileHash -LiteralPath $PortableZip -Algorithm SHA256).Hash
    UpdateSize = (Get-Item -LiteralPath $UpdateZip).Length
    UpdateSha256 = (Get-FileHash -LiteralPath $UpdateZip -Algorithm SHA256).Hash
  }
  if ($checks.Artifacts.UpdateSize -ge 100MB) {
    Add-Err ([ref]$errors) "Update zip is >= 100MB"
  }

  $portableEntries = Get-ZipEntries $PortableZip
  $badPortable = @($portableEntries | Where-Object {
      $_ -like "*.map" -or
      $_ -like "docs/*" -or $_ -like "*/docs/*" -or
      $_ -like "data/accounts/*.json"
    })
  $hasCompiledBackend = $portableEntries -contains "backend/autoscriptor-engine.exe"
  $hasSourceBackend = ($portableEntries -contains "backend/src/gui.py") -and ($portableEntries -contains "runtime/python/python.exe")
  $requiredPortable = @($LauncherName, "data/config.json")
  foreach ($entry in $requiredPortable) {
    if ($portableEntries -notcontains $entry) { Add-Err ([ref]$errors) "Portable zip missing $entry" }
  }
  if (-not ($hasCompiledBackend -or $hasSourceBackend)) {
    Add-Err ([ref]$errors) "Portable zip missing backend runtime (compiled engine or source backend)"
  }
  if ($badPortable.Count) { Add-Err ([ref]$errors) "Portable zip contains forbidden entries: $($badPortable -join ', ')" }

  $updateEntries = Get-ZipEntries $UpdateZip
  if ($updateEntries -notcontains "update_manifest.json") {
    Add-Err ([ref]$errors) "Update zip missing update_manifest.json"
  }
  if (-not (($updateEntries -contains "backend/autoscriptor-engine.exe") -or ($updateEntries -contains "backend/src/gui.py"))) {
    Add-Err ([ref]$errors) "Update zip missing backend payload"
  }
  if (@($updateEntries | Where-Object { $_ -like "*.map" -or $_ -like "docs/*" -or $_ -like "data/accounts/*.json" }).Count) {
    Add-Err ([ref]$errors) "Update zip contains forbidden entries"
  }

  Stop-TestProcesses $appRoot
  if (Test-Path -LiteralPath $WorkRoot) { Remove-Item -LiteralPath $WorkRoot -Recurse -Force }
  New-Item -ItemType Directory -Force -Path $appRoot | Out-Null

  if (Test-Path -LiteralPath $userDataRoot) {
    Move-Item -LiteralPath $userDataRoot -Destination $userDataBackup -Force
    $checks.UserDataBackup = $userDataBackup
  }

  Expand-Archive -LiteralPath $PortableZip -DestinationPath $appRoot -Force
  $launcher = Join-Path $appRoot $LauncherName
  if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw "Missing launcher after unzip: $launcher" }

  $startupSw = [System.Diagnostics.Stopwatch]::StartNew()
  $proc = Start-Process -FilePath $launcher -PassThru
  $windowMs = $null
  $deadline = (Get-Date).AddSeconds($WindowTimeoutSeconds)
  do {
    Start-Sleep -Milliseconds 200
    $p = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
    if ($p -and $p.MainWindowHandle -ne 0) {
      $windowMs = [int]$startupSw.ElapsedMilliseconds
      break
    }
  } while ((Get-Date) -lt $deadline -and $p)
  $checks.StartupWindow = @{ Pid = $proc.Id; WindowMs = $windowMs; UnderLimit = ($null -ne $windowMs -and $windowMs -lt ($WindowTimeoutSeconds * 1000)) }
  if ($null -eq $windowMs) { Add-Err ([ref]$errors) "No Electron window within $WindowTimeoutSeconds seconds" }

  $web = Wait-WebUi $WebUiTimeoutSeconds
  $checks.WebUi = $web
  if (-not $web.Ok) { Add-Err ([ref]$errors) "WebUI did not become ready: $($web.LastError)" }

  $markerPath = Join-Path $userDataRoot "install.json"
  if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) { throw "Missing install.json: $markerPath" }
  $marker = Get-Content -Raw -Encoding UTF8 -LiteralPath $markerPath | ConvertFrom-Json
  $dataRoot = [string]$marker.dataRoot
  $checks.InstallJson = @{ Path = $markerPath; installRoot = [string]$marker.installRoot; dataRoot = $dataRoot; version = [string]$marker.version }
  if ([string]$marker.installRoot -ne $appRoot) { Add-Err ([ref]$errors) "installRoot does not match app root" }
  if (-not $dataRoot -or -not (Test-Path -LiteralPath $dataRoot -PathType Container)) { Add-Err ([ref]$errors) "Invalid dataRoot" }

  $script:Session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
  $accountA = "std_accept_a"
  $accountB = "std_accept_b"
  $keyA = "std-key-a"
  $keyB = "std-key-b"
  $null = Invoke-Api "POST" "/accounts/add" @{ name = $accountA; account = "std_game_a"; password = "std_password_a"; server = "StdServer"; character_name = "RoleA"; security_key = $keyA }
  $null = Invoke-Api "POST" "/characters/add" @{ server = "StdServer"; character = "RoleA2" }
  $null = Invoke-Api "POST" "/accounts/add" @{ name = $accountB; account = "std_game_b"; password = "std_password_b"; server = "StdServer"; character_name = "RoleB"; security_key = $keyB }
  $null = Invoke-Api "POST" "/account" @{ account = "std_game_b_updated"; password = "std_password_b_updated"; security_key = "std-key-b2"; current_security_key = $keyB; confirmed = $true }
  $null = Invoke-Api "POST" "/credential/revoke" @{}
  $locked = Invoke-Api "GET" "/credential/status"
  $verify = Invoke-Api "POST" "/verify" @{ security_key = "std-key-b2" }
  $unlocked = Invoke-Api "GET" "/credential/status"
  $switch = Invoke-Api "POST" "/accounts/switch" @{ name = $accountA; security_key = $keyA }
  $checks.AccountsAndCredential = @{
    locked_after_revoke = $locked.unlocked
    verify_character = $verify.character_name
    unlocked_after_verify = $unlocked.unlocked
    switched_to = $switch.current_account
  }
  if ($locked.unlocked -ne $false) { Add-Err ([ref]$errors) "Credential revoke did not lock" }
  if ($unlocked.unlocked -ne $true) { Add-Err ([ref]$errors) "Credential verify did not unlock" }
  if ($switch.current_account -ne $accountA) { Add-Err ([ref]$errors) "Account switch failed" }

  $cfg = Invoke-Api "GET" "/refresh"
  $cfg.app.max_retry = 6
  $cfg.app.run_in_background = $true
  $cfg.emulator.index = 0
  $cfg.emulator.adb_addr = "127.0.0.1:16384"
  $null = Invoke-Api "POST" "/config" $cfg
  $savedCfg = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $dataRoot "config.json") | ConvertFrom-Json
  $checks.MachineSettings = @{
    max_retry = $savedCfg.app.max_retry
    run_in_background = $savedCfg.app.run_in_background
    index = $savedCfg.emulator.index
    adb_addr = $savedCfg.emulator.adb_addr
  }
  if ($savedCfg.app.max_retry -ne 6) { Add-Err ([ref]$errors) "max_retry did not persist" }
  if (-not [bool]$savedCfg.app.run_in_background) { Add-Err ([ref]$errors) "run_in_background did not persist" }

  $accountPath = Join-Path (Join-Path $dataRoot "accounts") "$accountA.json"
  if (-not (Test-Path -LiteralPath $accountPath -PathType Leaf)) {
    Add-Err ([ref]$errors) "Missing account json"
  } else {
    $accountJson = Get-Content -Raw -Encoding UTF8 -LiteralPath $accountPath | ConvertFrom-Json
    $roleCount = Count-Roles $accountJson
    $checks.AccountJson = @{ Path = $accountPath; RoleCount = $roleCount }
    if ($roleCount -lt 2) { Add-Err ([ref]$errors) "Expected account A to have at least two roles" }
  }

  try {
    $diag = Invoke-Api "GET" "/device/diagnostics?screenshot=false&require_app=false"
    $diagPath = Join-Path $logRoot "device-diagnostics.json"
    Write-JsonNoBom $diagPath $diag
    $checks.DeviceDiagnostics = @{
      Path = $diagPath
      ok = $diag.ok
      overall = if ($diag.diagnostics) { $diag.diagnostics.overall.status } else { "missing" }
    }
    if ($RequireDeviceDiagnostics -and ($diag.ok -ne $true -or $checks.DeviceDiagnostics.overall -eq "error")) {
      Add-Err ([ref]$errors) "Device diagnostics failed"
    }
  } catch {
    $warnings += "Device diagnostics request failed: $($_.Exception.Message)"
    if ($RequireDeviceDiagnostics) { Add-Err ([ref]$errors) "Device diagnostics request failed" }
  }
} catch {
  if (-not $errors.Count) { Add-Err ([ref]$errors) $_.Exception.Message }
  $checks.Exception = $_.Exception.Message
} finally {
  Stop-TestProcesses $appRoot
  if (-not $KeepTestUserData) {
    try {
      if (Test-Path -LiteralPath $userDataRoot) {
        Remove-Item -LiteralPath $userDataRoot -Recurse -Force
      }
      if (Test-Path -LiteralPath $userDataBackup) {
        Move-Item -LiteralPath $userDataBackup -Destination $userDataRoot -Force
        $report.RestoredUserData = $true
      }
    } catch {
      $warnings += "Failed to restore original userData: $($_.Exception.Message)"
    }
  }
  $report.Errors = $errors
  $report.Warnings = $warnings
  $report.Ok = ($errors.Count -eq 0)
  Write-JsonNoBom (Join-Path $logRoot "report.json") $report
  $report | ConvertTo-Json -Depth 80
}

if ($errors.Count) { exit 1 }
