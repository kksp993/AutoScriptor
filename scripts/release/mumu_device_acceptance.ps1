param(
  [string]$InstallRoot = "$env:USERPROFILE\Documents\AutoScriptor",
  [string]$OutDir = "$env:USERPROFILE\Desktop\AutoScriptorMuMuAcceptance",
  [int]$WebUiTimeoutSeconds = 240,
  [int]$ProbeTimeoutSeconds = 180,
  [switch]$RequireApp,
  [switch]$SkipStartProbe,
  [switch]$ExercisePowerCycle,
  [switch]$ExerciseScreenshot,
  [switch]$ShutdownAfter,
  [switch]$KeepWebUi
)

$ErrorActionPreference = "Stop"

function Write-Json($Path, $Object) {
  $Object | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Add-Error([ref]$Errors, [string]$Message) {
  $Errors.Value += $Message
}

function Invoke-EngineProbe {
  param(
    [string]$Engine,
    [string]$BackendDir,
    [string]$DataRoot,
    [string[]]$Arguments,
    [string]$StdoutPath
  )

  $oldData = $env:AUTOSCRIPTOR_DATA_DIR
  $oldUtf8 = $env:PYTHONUTF8
  $oldIo = $env:PYTHONIOENCODING
  $oldNoColor = $env:NO_COLOR
  try {
    $env:AUTOSCRIPTOR_DATA_DIR = $DataRoot
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:NO_COLOR = "1"
    Push-Location -LiteralPath $BackendDir
    try {
      $oldEap = $ErrorActionPreference
      $ErrorActionPreference = "Continue"
      $output = & $Engine @Arguments 2>&1
      $code = $LASTEXITCODE
      $ErrorActionPreference = $oldEap
    } finally {
      if ($null -ne $oldEap) {
        $ErrorActionPreference = $oldEap
      }
      Pop-Location
    }
    $output | Set-Content -LiteralPath $StdoutPath -Encoding UTF8
    return [ordered]@{
      ExitCode = $code
      StdoutPath = $StdoutPath
    }
  } finally {
    $env:AUTOSCRIPTOR_DATA_DIR = $oldData
    $env:PYTHONUTF8 = $oldUtf8
    $env:PYTHONIOENCODING = $oldIo
    $env:NO_COLOR = $oldNoColor
  }
}

function Wait-WebUi($Uri, [int]$TimeoutSeconds) {
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

function Get-Port5000Owners {
  $pids = @()
  try {
    $pids = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction Stop |
      Select-Object -ExpandProperty OwningProcess -Unique
  } catch {
    try {
      $lines = netstat -ano -p tcp | Select-String ":5000\s+.*LISTENING"
      foreach ($line in $lines) {
        $parts = ($line.ToString().Trim() -split "\s+")
        if ($parts.Count -gt 0) {
          $pids += [int]$parts[$parts.Count - 1]
        }
      }
      $pids = $pids | Select-Object -Unique
    } catch {
      return @([ordered]@{
        ProcessId = $null
        Name = "<unknown>"
        Path = ""
        CommandLine = "Failed to inspect port 5000: $($_.Exception.Message)"
      })
    }
  }

  $owners = @()
  foreach ($processId in $pids) {
    if (-not $processId) { continue }
    $proc = $null
    $cim = $null
    try { $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue } catch {}
    try { $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue } catch {}
    $owners += [ordered]@{
      ProcessId = [int]$processId
      Name = if ($proc) { $proc.ProcessName } else { "<unknown>" }
      Path = if ($cim) { $cim.ExecutablePath } else { "" }
      CommandLine = if ($cim) { $cim.CommandLine } else { "" }
    }
  }
  return @($owners)
}

function Invoke-ApiJson {
  param(
    [string]$Name,
    [string]$Uri,
    [string]$OutPath,
    [bool]$ExpectOk = $false,
    [string[]]$RequiredKeys = @()
  )

  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  try {
    $obj = Invoke-RestMethod -Uri $Uri -Method Get -TimeoutSec 60
    $sw.Stop()
    Write-Json $OutPath $obj

    $missing = @()
    foreach ($key in $RequiredKeys) {
      if ($null -eq $obj -or $null -eq $obj.PSObject.Properties[$key]) {
        $missing += $key
      }
    }

    $ok = $true
    $errorText = ""
    if ($ExpectOk -and $obj.ok -ne $true) {
      $ok = $false
      $errorText = "Expected JSON field ok=true"
    }
    if ($missing.Count -gt 0) {
      $ok = $false
      $errorText = "Missing required JSON key(s): $($missing -join ', ')"
    }

    return [ordered]@{
      Ok = $ok
      Name = $Name
      Uri = $Uri
      Path = $OutPath
      ElapsedMs = [int]$sw.ElapsedMilliseconds
      MissingKeys = $missing
      Error = $errorText
    }
  } catch {
    $sw.Stop()
    $_ | Out-File -Encoding UTF8 -Append -LiteralPath (Join-Path (Split-Path -Parent $OutPath) "diagnostics-error.log")
    return [ordered]@{
      Ok = $false
      Name = $Name
      Uri = $Uri
      Path = $OutPath
      ElapsedMs = [int]$sw.ElapsedMilliseconds
      MissingKeys = @()
      Error = $_.Exception.Message
    }
  }
}

function Get-Diagnostics($Screenshot, $RequireApp) {
  $screenshotText = if ($Screenshot) { "true" } else { "false" }
  $requireAppText = if ($RequireApp) { "true" } else { "false" }
  $uri = "http://127.0.0.1:5000/api/device/diagnostics?screenshot=$screenshotText&require_app=$requireAppText"
  return Invoke-RestMethod -Uri $uri -Method Get -TimeoutSec 60
}

function Test-MuMuConfigMapping($DataRoot) {
  $cfgPath = Join-Path $DataRoot "config.json"
  $result = [ordered]@{
    Checked = $false
    Ok = $true
    ConfigPath = $cfgPath
    ConfiguredIndex = $null
    AdbAddr = ""
    EmuPath = ""
    DetectedIndex = $null
    Match = $null
    Detail = ""
  }
  try {
    if (-not (Test-Path -LiteralPath $cfgPath -PathType Leaf)) {
      $result.Ok = $false
      $result.Detail = "config.json is missing"
      return $result
    }
    $cfg = Get-Content -Raw -LiteralPath $cfgPath -Encoding UTF8 | ConvertFrom-Json
    $emu = $cfg.emulator
    $result.ConfiguredIndex = $emu.index
    $result.AdbAddr = [string]$emu.adb_addr
    $result.EmuPath = [string]$emu.emu_path
    if (-not $result.EmuPath -or $result.EmuPath.StartsWith("YOUR_") -or -not (Test-Path -LiteralPath $result.EmuPath -PathType Leaf)) {
      $result.Ok = $false
      $result.Detail = "MuMuManager path is not valid"
      return $result
    }
    $portMatch = [regex]::Match($result.AdbAddr, ":(\d+)$")
    if (-not $result.AdbAddr -or $result.AdbAddr.StartsWith("YOUR_") -or $result.AdbAddr.EndsWith(":0") -or -not $portMatch.Success) {
      $result.Ok = $false
      $result.Detail = "ADB address is not configured"
      return $result
    }
    $port = $portMatch.Groups[1].Value
    $out = & $result.EmuPath info -v all 2>&1
    $code = $LASTEXITCODE
    if ($code -ne 0) {
      $result.Detail = "MuMuManager info -v all failed with exit code $code"
      return $result
    }
    $json = ($out | Out-String).Trim()
    $info = $json | ConvertFrom-Json
    $rows = @()
    if ($info -is [array]) {
      $rows = @($info)
    } elseif ($info.PSObject.Properties["index"]) {
      $rows = @($info)
    } else {
      foreach ($prop in $info.PSObject.Properties) {
        if ($prop.Value -and $prop.Value.PSObject.Properties["index"]) {
          $rows += $prop.Value
        }
      }
    }
    foreach ($row in $rows) {
      if ([string]$row.adb_port -eq [string]$port) {
        $result.DetectedIndex = $row.index
        break
      }
    }
    $result.Checked = $true
    if ($null -eq $result.DetectedIndex) {
      $result.Detail = "No MuMuManager info row matches ADB port $port"
      return $result
    }
    $result.Match = ([string]$result.ConfiguredIndex -eq [string]$result.DetectedIndex)
    if ($result.Match) {
      $result.Detail = "ADB port $port maps to configured MuMu index $($result.ConfiguredIndex)"
    } else {
      $result.Ok = $false
      $result.Detail = "Configured index $($result.ConfiguredIndex) does not match ADB port $port, which maps to MuMu index $($result.DetectedIndex)"
    }
    return $result
  } catch {
    $result.Detail = $_.Exception.Message
    return $result
  }
}

function Export-ProcessSnapshot($LogRoot, $InstallRoot) {
  try {
    $escapedRoot = [regex]::Escape($InstallRoot)
    Get-CimInstance Win32_Process |
      Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($InstallRoot, [System.StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and ($_.CommandLine -match $escapedRoot -or $_.CommandLine -match "autoscriptor|AutoScriptor"))
      } |
      Select-Object ProcessId, Name, ExecutablePath, CommandLine |
      Export-Csv -NoTypeInformation -Encoding UTF8 -LiteralPath (Join-Path $LogRoot "processes.csv")
  } catch {
    $_ | Out-File -Encoding UTF8 -Append -LiteralPath (Join-Path $LogRoot "diagnostics-error.log")
  }
}

function Stop-ProcessTree {
  param([int]$ProcessId)

  if (-not $ProcessId) { return }
  try {
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
      Stop-ProcessTree -ProcessId ([int]$child.ProcessId)
    }
  } catch {}

  try {
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
  } catch {}
}

function Stop-AcceptanceWebUi($Process, $InstallRoot) {
  if ($Process) {
    Stop-ProcessTree -ProcessId ([int]$Process.Id)
  }

  try {
    $escapedRoot = [regex]::Escape($InstallRoot)
    Get-CimInstance Win32_Process |
      Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($InstallRoot, [System.StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and $_.CommandLine -match $escapedRoot -and $_.CommandLine -match "autoscriptor-engine")
      } |
      ForEach-Object { Stop-ProcessTree -ProcessId ([int]$_.ProcessId) }
  } catch {}
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logRoot = Join-Path $OutDir "mumu_acceptance_$stamp"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

$errors = @()
$warnings = @()
$engine = Join-Path $InstallRoot "backend\autoscriptor-engine.exe"
$backendDir = Split-Path -Parent $engine
$dataRoot = Join-Path $InstallRoot "data"

$report = [ordered]@{
  Mode = "MuMuDeviceAcceptance"
  Time = (Get-Date).ToString("o")
  Computer = $env:COMPUTERNAME
  User = $env:USERNAME
  InstallRoot = $InstallRoot
  Engine = $engine
  DataRoot = $dataRoot
  LogRoot = $logRoot
  RequireApp = [bool]$RequireApp
  ExerciseStart = (-not [bool]$SkipStartProbe)
  ExercisePowerCycle = [bool]$ExercisePowerCycle
  ExerciseScreenshot = [bool]$ExerciseScreenshot
  ShutdownAfter = [bool]$ShutdownAfter
  Checks = [ordered]@{}
  Warnings = $warnings
  Errors = $errors
}

$webProc = $null
try {
  if (-not (Test-Path -LiteralPath $engine -PathType Leaf)) {
    Add-Error ([ref]$errors) "Missing packaged engine: $engine"
    throw "Packaged engine not found"
  }
  if (-not (Test-Path -LiteralPath (Join-Path $dataRoot "config.json") -PathType Leaf)) {
    Add-Error ([ref]$errors) "Missing data/config.json: $dataRoot"
    throw "Runtime data not found"
  }

  $mapping = Test-MuMuConfigMapping $dataRoot
  $report.Checks.MuMuConfigMapping = $mapping
  if ($mapping.Match -eq $false) {
    Add-Error ([ref]$errors) "MuMu config mismatch: $($mapping.Detail)"
  } elseif (-not $mapping.Checked) {
    $warnings += "MuMu config mapping was not fully checked: $($mapping.Detail)"
  }

  $portOwners = @(Get-Port5000Owners)
  $report.Checks.Port5000BeforeStart = $portOwners
  if ($portOwners.Count -gt 0) {
    Add-Error ([ref]$errors) "Port 5000 is already occupied before packaged WebUI start; close the listed process(es) and rerun. This prevents accidentally testing a dev server."
    throw "Port 5000 is already occupied"
  }

  $importReport = Join-Path $logRoot "runtime-import-smoke.json"
  $importStdout = Join-Path $logRoot "runtime-import-smoke.stdout.txt"
  $report.Checks.RuntimeImportSmoke = Invoke-EngineProbe `
    -Engine $engine `
    -BackendDir $backendDir `
    -DataRoot $dataRoot `
    -Arguments @("--runtime-import-smoke", "--probe-out", $importReport) `
    -StdoutPath $importStdout
  $report.Checks.RuntimeImportSmoke.ReportPath = $importReport
  if ($report.Checks.RuntimeImportSmoke.ExitCode -ne 0) {
    Add-Error ([ref]$errors) "Runtime import smoke failed; see $importReport"
  }

  $exerciseStart = (-not [bool]$SkipStartProbe)
  $needsMumuProbe = $exerciseStart -or [bool]$ExercisePowerCycle -or [bool]$ExerciseScreenshot
  if ($needsMumuProbe) {
    $mumuReport = Join-Path $logRoot "mumu-runtime-probe.json"
    $mumuStdout = Join-Path $logRoot "mumu-runtime-probe.stdout.txt"
    $probeArgs = @(
      "--mumu-runtime-probe",
      "--probe-out", $mumuReport,
      "--mumu-probe-timeout", ([string]$ProbeTimeoutSeconds),
      "--mumu-probe-start"
    )
    if ($RequireApp) { $probeArgs += "--mumu-probe-require-app" }
    if ($ExercisePowerCycle) { $probeArgs += "--mumu-probe-power-cycle" }
    if ($ExerciseScreenshot) { $probeArgs += "--mumu-probe-screenshot" }
    if ($ShutdownAfter) { $probeArgs += "--mumu-probe-shutdown-after" }

    $report.Checks.MuMuRuntimeProbe = Invoke-EngineProbe `
      -Engine $engine `
      -BackendDir $backendDir `
      -DataRoot $dataRoot `
      -Arguments $probeArgs `
      -StdoutPath $mumuStdout
    $report.Checks.MuMuRuntimeProbe.ReportPath = $mumuReport
    if ($report.Checks.MuMuRuntimeProbe.ExitCode -ne 0) {
      Add-Error ([ref]$errors) "MuMu runtime probe failed; see $mumuReport"
    }
    if (-not $ExercisePowerCycle) {
      $warnings += "MuMu start probe ran, but cold shutdown/start was not exercised. Pass -ExercisePowerCycle for full lifecycle validation."
    }
    if (-not $ExerciseScreenshot) {
      $warnings += "MuMu start probe ran, but NemuIpc screenshot was not exercised. Pass -ExerciseScreenshot for screenshot validation."
    }
  } else {
    $warnings += "Skipped MuMu start/power/screenshot probe because -SkipStartProbe was provided."
  }

  $oldData = $env:AUTOSCRIPTOR_DATA_DIR
  $oldUtf8 = $env:PYTHONUTF8
  $oldIo = $env:PYTHONIOENCODING
  $oldElectron = $env:AUTOSCRIPTOR_ELECTRON
  $oldPipe = $env:AUTOSCRIPTOR_ELECTRON_PIPE
  $oldNoColor = $env:NO_COLOR
  try {
    $env:AUTOSCRIPTOR_DATA_DIR = $dataRoot
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:AUTOSCRIPTOR_ELECTRON = "1"
    $env:AUTOSCRIPTOR_ELECTRON_PIPE = "1"
    $env:NO_COLOR = "1"
    $webProc = Start-Process -FilePath $engine -ArgumentList @("--electron") -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru
  } finally {
    $env:AUTOSCRIPTOR_DATA_DIR = $oldData
    $env:PYTHONUTF8 = $oldUtf8
    $env:PYTHONIOENCODING = $oldIo
    $env:AUTOSCRIPTOR_ELECTRON = $oldElectron
    $env:AUTOSCRIPTOR_ELECTRON_PIPE = $oldPipe
    $env:NO_COLOR = $oldNoColor
  }

  $report.Checks.WebUiProcessId = $webProc.Id
  $web = Wait-WebUi "http://127.0.0.1:5000" $WebUiTimeoutSeconds
  $report.Checks.WebUi = $web
  if (-not $web.Ok) {
    Add-Error ([ref]$errors) "WebUI did not respond within ${WebUiTimeoutSeconds}s: $($web.LastError)"
  } elseif ($webProc.HasExited) {
    Add-Error ([ref]$errors) "Packaged WebUI process exited unexpectedly with code $($webProc.ExitCode)"
  } else {
    $apiChecks = @(
      @{
        Key = "WebUiRefresh"
        Name = "refresh"
        Uri = "http://127.0.0.1:5000/api/refresh"
        ExpectOk = $false
        RequiredKeys = @("tasks", "emulator", "config_version")
      },
      @{
        Key = "WebUiRuntimeSnapshot"
        Name = "runtime-snapshot"
        Uri = "http://127.0.0.1:5000/api/runtime/snapshot"
        ExpectOk = $true
        RequiredKeys = @("runtime", "scheduler", "config_version")
      },
      @{
        Key = "WebUiOverview"
        Name = "overview"
        Uri = "http://127.0.0.1:5000/api/overview"
        ExpectOk = $false
        RequiredKeys = @("runtime", "scheduler", "stats")
      }
    )
    foreach ($check in $apiChecks) {
      $apiPath = Join-Path $logRoot "$($check.Name).json"
      $apiResult = Invoke-ApiJson `
        -Name $check.Name `
        -Uri $check.Uri `
        -OutPath $apiPath `
        -ExpectOk ([bool]$check.ExpectOk) `
        -RequiredKeys $check.RequiredKeys
      $report.Checks[$check.Key] = $apiResult
      if (-not $apiResult.Ok) {
        Add-Error ([ref]$errors) "WebUI API $($check.Name) failed: $($apiResult.Error); see $apiPath"
      }
    }

    $diag = Get-Diagnostics -Screenshot:$ExerciseScreenshot -RequireApp:$RequireApp
    $diagPath = Join-Path $logRoot "webui-device-diagnostics.json"
    Write-Json $diagPath $diag
    $overall = if ($diag.diagnostics) { $diag.diagnostics.overall.status } else { "missing" }
    $deviceOverall = if ($diag.diagnostics) { $diag.diagnostics.device_overall.status } else { "missing" }
    $taskOverall = if ($diag.diagnostics) { $diag.diagnostics.task_overall.status } else { "missing" }
    $report.Checks.WebUiDiagnostics = [ordered]@{
      Path = $diagPath
      Overall = $overall
      DeviceOverall = $deviceOverall
      TaskOverall = $taskOverall
    }
    if ($diag.ok -ne $true) {
      Add-Error ([ref]$errors) "WebUI diagnostics API did not return ok=true; see $diagPath"
    }
    if ($overall -eq "error") {
      Add-Error ([ref]$errors) "WebUI diagnostics overall is error; see $diagPath"
    }
  }

  Export-ProcessSnapshot $logRoot $InstallRoot
} catch {
  if (-not $errors.Count) {
    Add-Error ([ref]$errors) $_.Exception.Message
  }
  $report.Checks.Exception = $_.Exception.Message
} finally {
  if ($webProc -and -not $KeepWebUi) {
    Stop-AcceptanceWebUi $webProc $InstallRoot
  }
  $report.Errors = $errors
  $report.Warnings = $warnings
  $report.Ok = ($errors.Count -eq 0)
  Write-Json (Join-Path $logRoot "report.json") $report
  $report
}

if ($errors.Count) { exit 1 }
