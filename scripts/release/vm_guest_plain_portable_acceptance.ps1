param(
  [string]$InstallerPath = "\\VBOXSVR\release\AutoScriptor_Zao_Plain_Install_1.0.2.exe",
  [string]$InstallRoot = "$env:LOCALAPPDATA\AutoScriptorPlainVm",
  [string]$OutDir = "\\VBOXSVR\release\logs",
  [int]$InstallTimeoutSeconds = 900,
  [int]$WebUiTimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"
$DailyLauncherName = "$([char]0x9020)$([char]0x7b14).exe"

function Write-JsonNoBom($Path, $Object) {
  $json = $Object | ConvertTo-Json -Depth 80
  [System.IO.File]::WriteAllText($Path, $json, [System.Text.UTF8Encoding]::new($false))
}

function Add-Err([ref]$Errors, [string]$Message) {
  $Errors.Value += $Message
}

function Stop-AutoScriptorProcesses {
  foreach ($name in @($script:DailyLauncherName, "autoscriptor-engine.exe")) {
    try { & "$env:SystemRoot\System32\taskkill.exe" /IM $name /T /F 2>$null | Out-Null } catch {}
  }
  try {
    Get-CimInstance Win32_Process -OperationTimeoutSec 10 |
      Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($InstallRoot, [System.StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($InstallRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
      } |
      ForEach-Object { & "$env:SystemRoot\System32\taskkill.exe" /PID $_.ProcessId /T /F 2>$null | Out-Null }
  } catch {}
}

function Wait-WebUi($Uri, [int]$TimeoutSeconds) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $attempts = 0
  $last = ""
  $swTotal = [System.Diagnostics.Stopwatch]::StartNew()
  while ((Get-Date) -lt $deadline) {
    $attempts += 1
    try {
      $resp = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 5
      if ([int]$resp.StatusCode -eq 200) {
        $swTotal.Stop()
        return @{ Ok = $true; Attempts = $attempts; StatusCode = [int]$resp.StatusCode; ElapsedMs = [int]$swTotal.ElapsedMilliseconds; LastError = "" }
      }
    } catch {
      $last = $_.Exception.Message
    }
    Start-Sleep -Seconds 2
  }
  $swTotal.Stop()
  return @{ Ok = $false; Attempts = $attempts; StatusCode = $null; ElapsedMs = [int]$swTotal.ElapsedMilliseconds; LastError = $last }
}

function Invoke-Api($Method, $Path, $Body = $null) {
  $uri = "http://127.0.0.1:5000/api$Path"
  $headers = @{ "Content-Type" = "application/json" }
  $args = @{
    Uri = $uri
    Method = $Method
    UseBasicParsing = $true
    TimeoutSec = 45
    WebSession = $script:Session
  }
  if ($null -ne $Body) {
    if ($Body -is [hashtable]) {
      $Body["_timestamp"] = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    }
    $args.Headers = $headers
    $args.Body = ($Body | ConvertTo-Json -Depth 80)
  }
  try {
    $resp = Invoke-WebRequest @args
    if ($resp.Content) { return ($resp.Content | ConvertFrom-Json) }
    return $null
  } catch {
    $bodyText = ""
    try {
      $stream = $_.Exception.Response.GetResponseStream()
      if ($stream) {
        $reader = [System.IO.StreamReader]::new($stream)
        $bodyText = $reader.ReadToEnd()
      }
    } catch {}
    throw "API $Method $Path failed: $($_.Exception.Message) $bodyText"
  }
}

function Find-MuMuManager {
  $roots = @(
    (Join-Path $env:ProgramFiles "Netease"),
    (Join-Path ${env:ProgramFiles(x86)} "Netease"),
    (Join-Path $env:LOCALAPPDATA "Netease"),
    (Join-Path $env:ProgramData "Netease")
  ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) }
  $found = @()
  foreach ($root in $roots) {
    $found += Get-ChildItem -LiteralPath $root -Recurse -Filter "MuMuManager.exe" -ErrorAction SilentlyContinue |
      Select-Object -First 5 FullName, Length, LastWriteTime
  }
  return @($found)
}

function Get-MuMuInfo($ManagerPath) {
  $result = [ordered]@{ ManagerPath = $ManagerPath; VersionText = ""; InfoOk = $false; InfoText = ""; Error = "" }
  try {
    $ver = & $ManagerPath version 2>&1
    $result.VersionText = ($ver | Out-String).Trim()
  } catch {
    $result.Error = "version failed: $($_.Exception.Message)"
  }
  try {
    $info = & $ManagerPath info -v all 2>&1
    $result.InfoText = ($info | Out-String).Trim()
    $result.InfoOk = ($LASTEXITCODE -eq 0 -and $result.InfoText)
  } catch {
    $result.Error = ($result.Error + " info failed: $($_.Exception.Message)").Trim()
  }
  return $result
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

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logRoot = Join-Path $OutDir "plain_portable_acceptance_$stamp"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

$errors = @()
$warnings = @()
$checks = [ordered]@{}
$report = [ordered]@{
  Mode = "PlainPortableAcceptance"
  Time = (Get-Date).ToString("o")
  Computer = $env:COMPUTERNAME
  User = $env:USERNAME
  InstallerPath = $InstallerPath
  InstallRoot = $InstallRoot
  LogRoot = $logRoot
  Checks = $checks
  Errors = $errors
  Warnings = $warnings
}

try {
  if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    throw "Missing installer: $InstallerPath"
  }

  Stop-AutoScriptorProcesses
  if (Test-Path -LiteralPath $InstallRoot) {
    Remove-Item -LiteralPath $InstallRoot -Recurse -Force
  }
  $userDataRoot = Join-Path $env:APPDATA "autoscriptor"
  if (Test-Path -LiteralPath $userDataRoot) {
    Remove-Item -LiteralPath $userDataRoot -Recurse -Force
  }

  $checks.InstallerSha256 = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash
  $installSw = [System.Diagnostics.Stopwatch]::StartNew()
  $proc = Start-Process -FilePath $InstallerPath -ArgumentList @("/S", "/D=$InstallRoot") -PassThru
  $finished = $proc.WaitForExit([Math]::Max(1, $InstallTimeoutSeconds) * 1000)
  $installSw.Stop()
  $checks.SilentInstall = @{ Finished = $finished; ExitCode = if ($finished) { $proc.ExitCode } else { $null }; ElapsedMs = [int]$installSw.ElapsedMilliseconds }
  if (-not $finished) {
    try { & "$env:SystemRoot\System32\taskkill.exe" /PID $proc.Id /T /F 2>$null | Out-Null } catch {}
    throw "Plain NSIS install timed out"
  }
  if ($proc.ExitCode -ne 0) {
    throw "Plain NSIS install exit code: $($proc.ExitCode)"
  }

  $launcher = Join-Path $InstallRoot $DailyLauncherName
  if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    $fallback = Get-ChildItem -LiteralPath $env:LOCALAPPDATA -Recurse -Filter $DailyLauncherName -ErrorAction SilentlyContinue |
      Where-Object { Test-Path -LiteralPath (Join-Path $_.DirectoryName "backend\autoscriptor-engine.exe") -PathType Leaf } |
      Select-Object -First 1
    if ($fallback) {
      $launcher = $fallback.FullName
      $InstallRoot = $fallback.DirectoryName
      $report.InstallRoot = $InstallRoot
      $warnings += "Installer ignored requested /D path; using detected install root: $InstallRoot"
    }
  }
  if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Missing launcher after install: $launcher"
  }
  $checks.LauncherPath = $launcher

  $launchSw = [System.Diagnostics.Stopwatch]::StartNew()
  $app = Start-Process -FilePath $launcher -PassThru
  $checks.LauncherPid = $app.Id
  Start-Sleep -Seconds 3
  $procAliveAfter3s = -not $app.HasExited
  $checks.StartupResponsiveness = @{
    ProcessAliveAfter3s = $procAliveAfter3s
    MainWindowTitleAfter3s = (Get-Process -Id $app.Id -ErrorAction SilentlyContinue).MainWindowTitle
  }
  if (-not $procAliveAfter3s) {
    Add-Err ([ref]$errors) "Launcher exited within 3 seconds"
  }
  $web = Wait-WebUi "http://127.0.0.1:5000/api/refresh" $WebUiTimeoutSeconds
  $launchSw.Stop()
  $checks.WebUiStartup = $web
  $checks.StartupElapsedMs = [int]$launchSw.ElapsedMilliseconds
  if (-not $web.Ok) {
    Add-Err ([ref]$errors) "WebUI did not become ready: $($web.LastError)"
    throw "WebUI startup failed"
  }
  if ($web.ElapsedMs -gt 120000) {
    $warnings += "WebUI startup took more than 120 seconds; consider more visible async startup feedback."
  }

  $markerPath = Join-Path $userDataRoot "install.json"
  if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
    Add-Err ([ref]$errors) "Missing install marker: $markerPath"
    throw "Missing install marker"
  }
  $marker = Get-Content -Raw -Encoding UTF8 -LiteralPath $markerPath | ConvertFrom-Json
  $dataRoot = [string]$marker.dataRoot
  $checks.InstallJson = @{ Path = $markerPath; installRoot = [string]$marker.installRoot; dataRoot = $dataRoot; version = [string]$marker.version }
  if (-not $dataRoot -or -not (Test-Path -LiteralPath $dataRoot -PathType Container)) {
    Add-Err ([ref]$errors) "Invalid dataRoot: $dataRoot"
  }

  $script:Session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
  $refresh = Invoke-Api "GET" "/refresh"
  $checks.RefreshKeys = @($refresh.PSObject.Properties.Name)

  $accountA = "vm_plain_a"
  $accountB = "vm_plain_b"
  $keyA = "plain-key-a"
  $keyB = "plain-key-b"
  $null = Invoke-Api "POST" "/accounts/add" @{ name = $accountA; account = "plain_game_a"; password = "plain_password_a"; server = "VMServer"; character_name = "RoleA"; security_key = $keyA }
  $null = Invoke-Api "POST" "/characters/add" @{ server = "VMServer"; character = "RoleA2" }
  $null = Invoke-Api "POST" "/accounts/add" @{ name = $accountB; account = "plain_game_b"; password = "plain_password_b"; server = "VMServer"; character_name = "RoleB"; security_key = $keyB }
  $accountsAfterAdd = Invoke-Api "GET" "/accounts"
  $checks.AccountsAfterAdd = $accountsAfterAdd
  if (@($accountsAfterAdd.accounts) -notcontains $accountA -or @($accountsAfterAdd.accounts) -notcontains $accountB) {
    Add-Err ([ref]$errors) "Added accounts are missing from /api/accounts"
  }

  $null = Invoke-Api "POST" "/account" @{ account = "plain_game_b_updated"; password = "plain_password_b_updated"; security_key = "plain-key-b2"; current_security_key = $keyB; confirmed = $true }
  $null = Invoke-Api "POST" "/credential/revoke" @{}
  $statusLocked = Invoke-Api "GET" "/credential/status"
  $verify = Invoke-Api "POST" "/verify" @{ security_key = "plain-key-b2" }
  $statusUnlocked = Invoke-Api "GET" "/credential/status"
  $switchA = Invoke-Api "POST" "/accounts/switch" @{ name = $accountA; security_key = $keyA }
  $checks.CredentialFlow = @{
    locked_after_revoke = $statusLocked.unlocked
    verify_character = $verify.character_name
    unlocked_after_verify = $statusUnlocked.unlocked
    switched_to = $switchA.current_account
  }
  if ($statusLocked.unlocked -ne $false) { Add-Err ([ref]$errors) "Credential revoke did not lock credentials" }
  if ($statusUnlocked.unlocked -ne $true) { Add-Err ([ref]$errors) "Verify did not unlock credentials" }
  if ($switchA.current_account -ne $accountA) { Add-Err ([ref]$errors) "Switch account did not switch to $accountA" }

  $cfg = Invoke-Api "GET" "/refresh"
  $mumuManagers = @(Find-MuMuManager)
  $mumuInfo = $null
  if ($mumuManagers.Count -gt 0) {
    $mumuInfo = Get-MuMuInfo $mumuManagers[0].FullName
    $cfg.emulator.mumu_folder = (Split-Path -Parent (Split-Path -Parent $mumuManagers[0].FullName))
    $cfg.emulator.emu_path = $mumuManagers[0].FullName
  } else {
    $warnings += "MuMuManager.exe was not found in this VM; device diagnostics cannot fully pass."
  }
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
    mumu_folder = $savedCfg.emulator.mumu_folder
    emu_path = $savedCfg.emulator.emu_path
  }
  if ($savedCfg.app.max_retry -ne 6) { Add-Err ([ref]$errors) "app.max_retry did not persist" }
  if (-not [bool]$savedCfg.app.run_in_background) { Add-Err ([ref]$errors) "app.run_in_background did not persist" }

  $accountAPath = Join-Path (Join-Path $dataRoot "accounts") "$accountA.json"
  if (Test-Path -LiteralPath $accountAPath -PathType Leaf) {
    $accountJson = Get-Content -Raw -Encoding UTF8 -LiteralPath $accountAPath | ConvertFrom-Json
    $checks.AccountAJson = @{ Path = $accountAPath; RoleCount = Count-Roles $accountJson }
    if ($checks.AccountAJson.RoleCount -lt 2) { Add-Err ([ref]$errors) "Expected account A to have at least 2 roles" }
  } else {
    Add-Err ([ref]$errors) "Missing account A JSON: $accountAPath"
  }

  $diag = Invoke-Api "GET" "/device/diagnostics?screenshot=false&require_app=false"
  $diagPath = Join-Path $logRoot "device-diagnostics.json"
  Write-JsonNoBom $diagPath $diag
  $checks.MuMu = @{ Managers = $mumuManagers; Info = $mumuInfo }
  $checks.DeviceDiagnostics = @{
    Path = $diagPath
    ok = $diag.ok
    overall = if ($diag.diagnostics) { $diag.diagnostics.overall.status } else { "missing" }
    device_overall = if ($diag.diagnostics) { $diag.diagnostics.device_overall.status } else { "missing" }
    task_overall = if ($diag.diagnostics) { $diag.diagnostics.task_overall.status } else { "missing" }
  }
  if ($mumuManagers.Count -eq 0) {
    Add-Err ([ref]$errors) "MuMuManager.exe was not found; cannot complete MuMu control-module acceptance"
  } elseif ($diag.ok -ne $true -or $checks.DeviceDiagnostics.overall -eq "error") {
    Add-Err ([ref]$errors) "Device diagnostics did not fully pass; see $diagPath"
  }
} catch {
  if (-not $errors.Count) { Add-Err ([ref]$errors) $_.Exception.Message }
  $checks.Exception = $_.Exception.Message
} finally {
  try {
    VBoxTray.exe | Out-Null
  } catch {}
  $report.Errors = $errors
  $report.Warnings = $warnings
  $report.Ok = ($errors.Count -eq 0)
  Write-JsonNoBom (Join-Path $logRoot "report.json") $report
  $report
}

if ($errors.Count) { exit 1 }
