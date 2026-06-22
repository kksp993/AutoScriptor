param(
  [string]$InstallRoot = "$env:LOCALAPPDATA\AutoScriptorVmAcceptance",
  [string]$OutDir = "\\VBOXSVR\release\logs",
  [int]$WebUiTimeoutSeconds = 240
)

$ErrorActionPreference = "Stop"

function Write-JsonNoBom($Path, $Object) {
  $json = $Object | ConvertTo-Json -Depth 60
  [System.IO.File]::WriteAllText($Path, $json, [System.Text.UTF8Encoding]::new($false))
}

function Add-Err([ref]$Errors, [string]$Message) {
  $Errors.Value += $Message
}

function Wait-Condition([scriptblock]$Condition, [int]$TimeoutSeconds = 60, [int]$PollSeconds = 2) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if (& $Condition) { return $true }
    Start-Sleep -Seconds $PollSeconds
  }
  return (& $Condition)
}

function Wait-WebUi($Uri, [int]$TimeoutSeconds) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $last = ""
  while ((Get-Date) -lt $deadline) {
    try {
      $resp = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 5
      if ([int]$resp.StatusCode -eq 200) { return @{ Ok = $true; LastError = "" } }
    } catch {
      $last = $_.Exception.Message
    }
    Start-Sleep -Seconds 2
  }
  return @{ Ok = $false; LastError = $last }
}

function Invoke-Api($Method, $Path, $Body = $null) {
  $uri = "http://127.0.0.1:5000/api$Path"
  $headers = @{ "Content-Type" = "application/json" }
  try {
    if ($null -eq $Body) {
      $resp = Invoke-WebRequest -Uri $uri -Method $Method -UseBasicParsing -TimeoutSec 30
    } else {
      $payload = $Body | ConvertTo-Json -Depth 80
      $resp = Invoke-WebRequest -Uri $uri -Method $Method -Headers $headers -Body $payload -UseBasicParsing -TimeoutSec 30
    }
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

function Get-Props($Object) {
  if ($null -eq $Object) { return @() }
  return @($Object.PSObject.Properties)
}

function Find-TaskLeaf($Node, [string]$Prefix, [switch]$PreferParams) {
  foreach ($prop in Get-Props $Node) {
    $name = $prop.Name
    $value = $prop.Value
    if ($null -eq $value -or $value -isnot [psobject]) { continue }
    $path = if ($Prefix) { "$Prefix/$name" } else { $name }
    $hasOn = $null -ne ($value.PSObject.Properties["on"])
    $hasParams = $null -ne ($value.PSObject.Properties["params"])
    if ($hasOn -and ((-not $PreferParams) -or $hasParams)) {
      return @{ Path = $path; Leaf = $value; HasParams = $hasParams }
    }
    $found = Find-TaskLeaf $value $path -PreferParams:$PreferParams
    if ($found) { return $found }
  }
  return $null
}

function Set-FirstParamValue($Leaf) {
  $paramsProp = $Leaf.PSObject.Properties["params"]
  if ($null -eq $paramsProp -or $null -eq $paramsProp.Value) {
    return @{ Changed = $false; Key = ""; Value = $null }
  }
  foreach ($p in Get-Props $paramsProp.Value) {
    $old = $p.Value
    if ($old -is [bool]) {
      $p.Value = -not $old
    } elseif ($old -is [int] -or $old -is [long] -or $old -is [double]) {
      $p.Value = $old + 1
    } elseif ($old -is [string]) {
      $p.Value = if ($old) { "$old-vm" } else { "vm" }
    } else {
      continue
    }
    return @{ Changed = $true; Key = $p.Name; Value = $p.Value }
  }
  return @{ Changed = $false; Key = ""; Value = $null }
}

function Test-TaskPathOn($Node, [string]$Path) {
  $cur = $Node
  foreach ($part in ($Path -split "/")) {
    if (-not $part) { continue }
    $prop = $cur.PSObject.Properties[$part]
    if ($null -eq $prop) { return $false }
    $cur = $prop.Value
  }
  $onProp = $cur.PSObject.Properties["on"]
  return ($null -ne $onProp -and [bool]$onProp.Value)
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logRoot = Join-Path $OutDir "user_workflow_$stamp"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

$errors = @()
$warnings = @()
$checks = [ordered]@{}
$report = [ordered]@{
  Mode = "UserWorkflowAcceptance"
  Time = (Get-Date).ToString("o")
  Computer = $env:COMPUTERNAME
  User = $env:USERNAME
  InstallRoot = $InstallRoot
  LogRoot = $logRoot
  Checks = $checks
  Errors = $errors
  Warnings = $warnings
}

try {
  $dailyLauncher = Join-Path $InstallRoot "$([char]0x9020)$([char]0x7b14).exe"
  if (-not (Test-Path -LiteralPath $dailyLauncher -PathType Leaf)) {
    Add-Err ([ref]$errors) "Missing daily launcher: $dailyLauncher"
    throw "Missing daily launcher"
  }

  $proc = Start-Process -FilePath $dailyLauncher -PassThru
  $checks.LauncherPid = $proc.Id
  $web = Wait-WebUi "http://127.0.0.1:5000/api/refresh" $WebUiTimeoutSeconds
  $checks.WebUi = $web
  if (-not $web.Ok) {
    Add-Err ([ref]$errors) "WebUI did not become ready: $($web.LastError)"
    throw "WebUI timeout"
  }

  $markerPath = Join-Path $env:APPDATA "autoscriptor\install.json"
  if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
    Add-Err ([ref]$errors) "Missing install marker: $markerPath"
    throw "Missing install marker"
  }
  $marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
  $dataRoot = [string]$marker.dataRoot
  $checks.InstallJson = @{
    installRoot = [string]$marker.installRoot
    dataRoot = $dataRoot
    version = [string]$marker.version
  }
  if (-not $dataRoot -or -not (Test-Path -LiteralPath $dataRoot -PathType Container)) {
    Add-Err ([ref]$errors) "Invalid dataRoot in install.json: $dataRoot"
    throw "Invalid dataRoot"
  }

  $accountName = "vm_acceptance_102"
  $securityKey = "vm-key-102"
  $null = Invoke-Api "POST" "/accounts/add" @{
    name = $accountName
    account = "vm_game_account"
    password = "vm_game_password"
    server = "VM服务器"
    character_name = "VM角色A"
    security_key = $securityKey
  }
  $null = Invoke-Api "POST" "/characters/add" @{ server = "VM服务器"; character = "VM角色B" }
  $null = Invoke-Api "POST" "/characters/add" @{ server = "VM服务器"; character = "VM角色C" }

  $cfg = Invoke-Api "GET" "/refresh"
  $taskPick = Find-TaskLeaf $cfg.tasks "" -PreferParams
  if (-not $taskPick) { $taskPick = Find-TaskLeaf $cfg.tasks "" }
  if (-not $taskPick) {
    Add-Err ([ref]$errors) "No task leaf found in /api/refresh payload"
    throw "No task leaf"
  }
  $taskPick.Leaf.on = $true
  $paramChange = Set-FirstParamValue $taskPick.Leaf
  $savedTasks = Invoke-Api "POST" "/tasks" @{ tasks = $cfg.tasks }
  $checks.SavedTaskPath = $taskPick.Path
  $checks.TaskParamChange = $paramChange
  if (-not (Test-TaskPathOn $savedTasks.tasks $taskPick.Path)) {
    Add-Err ([ref]$errors) "Saved task did not remain enabled in API response: $($taskPick.Path)"
  }

  $cfg2 = Invoke-Api "GET" "/refresh"
  $cfg2.app.max_retry = 7
  $cfg2.app.run_in_background = $true
  $cfg2.emulator.index = 2
  $cfg2.emulator.adb_addr = "127.0.0.1:16448"
  $cfg2.emulator.mumu_folder = "C:\VM\MuMu"
  $cfg2.emulator.emu_path = "C:\VM\MuMu\nx_main\MuMuManager.exe"
  $cfg2.emulator.adb_path = "C:\VM\MuMu\nx_main\adb.exe"
  $null = Invoke-Api "POST" "/config" $cfg2

  $configPath = Join-Path $dataRoot "config.json"
  $accountPath = Join-Path (Join-Path $dataRoot "accounts") "$accountName.json"
  $checks.ConfigPath = $configPath
  $checks.AccountPath = $accountPath
  if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    Add-Err ([ref]$errors) "Missing dataRoot config after save: $configPath"
  }
  if (-not (Test-Path -LiteralPath $accountPath -PathType Leaf)) {
    Add-Err ([ref]$errors) "Missing account JSON after account creation: $accountPath"
  }
  $savedCfg = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
  $checks.MachineSettings = @{
    max_retry = $savedCfg.app.max_retry
    run_in_background = $savedCfg.app.run_in_background
    index = $savedCfg.emulator.index
    adb_addr = $savedCfg.emulator.adb_addr
    mumu_folder = $savedCfg.emulator.mumu_folder
    emu_path = $savedCfg.emulator.emu_path
    adb_path = $savedCfg.emulator.adb_path
  }
  if ($savedCfg.app.max_retry -ne 7) { Add-Err ([ref]$errors) "app.max_retry did not persist" }
  if (-not [bool]$savedCfg.app.run_in_background) { Add-Err ([ref]$errors) "app.run_in_background did not persist" }
  if ([int]$savedCfg.emulator.index -ne 2) { Add-Err ([ref]$errors) "emulator.index did not persist" }
  if ([string]$savedCfg.emulator.adb_addr -ne "127.0.0.1:16448") { Add-Err ([ref]$errors) "emulator.adb_addr did not persist" }
  if ([string]$savedCfg.emulator.mumu_folder -ne "C:\VM\MuMu") { Add-Err ([ref]$errors) "emulator.mumu_folder did not persist" }
  if ([string]$savedCfg.emulator.emu_path -ne "C:\VM\MuMu\nx_main\MuMuManager.exe") { Add-Err ([ref]$errors) "emulator.emu_path did not persist" }
  if ([string]$savedCfg.emulator.adb_path -ne "C:\VM\MuMu\nx_main\adb.exe") { Add-Err ([ref]$errors) "emulator.adb_path did not persist" }

  if (Test-Path -LiteralPath $accountPath -PathType Leaf) {
    $accountJson = Get-Content -LiteralPath $accountPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $roleCount = 0
    foreach ($serverProp in Get-Props $accountJson.characters) {
      $roleCount += @(Get-Props $serverProp.Value).Count
    }
    $checks.RoleCount = $roleCount
    if ($roleCount -lt 3) { Add-Err ([ref]$errors) "Expected initial role plus two added roles, got $roleCount" }
    if (-not (Test-TaskPathOn $accountJson.characters."VM服务器"."VM角色A".tasks $taskPick.Path)) {
      Add-Err ([ref]$errors) "Saved task not persisted to account JSON: $($taskPick.Path)"
    }
  }

  $uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoScriptorZao"
  if (-not (Test-Path -LiteralPath $uninstallKey)) {
    Add-Err ([ref]$errors) "Windows Apps uninstall registry key missing: $uninstallKey"
    throw "Missing uninstall registry"
  }
  $un = Get-ItemProperty -LiteralPath $uninstallKey
  $checks.UninstallRegistry = @{
    DisplayName = [string]$un.DisplayName
    DisplayVersion = [string]$un.DisplayVersion
    InstallLocation = [string]$un.InstallLocation
    UninstallString = [string]$un.UninstallString
    EstimatedSize = [int]$un.EstimatedSize
    NoModify = [int]$un.NoModify
    NoRepair = [int]$un.NoRepair
  }
  if ($un.DisplayName -ne "造笔") { Add-Err ([ref]$errors) "Unexpected uninstall DisplayName: $($un.DisplayName)" }
  if (-not $un.UninstallString -or $un.UninstallString -notmatch "Uninstall\.ps1") {
    Add-Err ([ref]$errors) "UninstallString does not point to Uninstall.ps1: $($un.UninstallString)"
  }
  if ([int]$un.EstimatedSize -le 0) { Add-Err ([ref]$errors) "EstimatedSize missing or zero" }
  if ([int]$un.NoModify -ne 1 -or [int]$un.NoRepair -ne 1) {
    Add-Err ([ref]$errors) "NoModify/NoRepair are not set"
  }

  if ($errors.Count -eq 0) {
    cmd.exe /c $un.UninstallString | Out-Null
    $checks.UninstallRemovedBackend = Wait-Condition { -not (Test-Path -LiteralPath (Join-Path $InstallRoot "backend")) } 60 2
    $checks.UninstallRemovedRegistry = Wait-Condition { -not (Test-Path -LiteralPath $uninstallKey) } 60 2
    $checks.UninstallRemovedMarker = Wait-Condition { -not (Test-Path -LiteralPath $markerPath) } 60 2
    $checks.UninstallPreservedDataRoot = Test-Path -LiteralPath $dataRoot -PathType Container
    if (-not $checks.UninstallRemovedBackend) { Add-Err ([ref]$errors) "UninstallString did not remove backend directory" }
    if (-not $checks.UninstallRemovedRegistry) { Add-Err ([ref]$errors) "UninstallString did not remove registry key" }
    if (-not $checks.UninstallRemovedMarker) { Add-Err ([ref]$errors) "UninstallString did not remove install.json" }
    if (-not $checks.UninstallPreservedDataRoot) { Add-Err ([ref]$errors) "Default uninstall should preserve dataRoot" }
  }
} catch {
  if (-not $errors.Count) { Add-Err ([ref]$errors) $_.Exception.Message }
  $checks.Exception = $_.Exception.Message
} finally {
  $report.Errors = $errors
  $report.Warnings = $warnings
  $report.Ok = ($errors.Count -eq 0)
  Write-JsonNoBom (Join-Path $logRoot "report.json") $report
  $report
}

if ($errors.Count) { exit 1 }
