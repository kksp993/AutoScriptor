param(
  [string]$InstallerPath = "\\VBOXSVR\release\MuMu_latest_gw_win.exe",
  [string[]]$InstallerArgs = @("/S"),
  [string]$OutDir = "\\VBOXSVR\release\logs",
  [int]$TimeoutSeconds = 1800,
  [int]$PollSeconds = 5,
  [switch]$UseScheduledTask,
  [string]$TaskPassword = "",
  [switch]$KillOnTimeout
)

$ErrorActionPreference = "Stop"

function Write-Json($Path, $Object) {
  $Object | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
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
      Select-Object FullName, Length, LastWriteTime
  }
  return @($found)
}

function Get-MuMuProcesses {
  Get-CimInstance Win32_Process |
    Where-Object {
      ($_.Name -match "mumu|nemu|netease") -or
      ($_.CommandLine -match "mumu|nemu|netease")
    } |
    Select-Object ProcessId, Name, ExecutablePath, CommandLine
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logRoot = Join-Path $OutDir "mumu_install_$stamp"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

$errors = @()
$warnings = @()
$report = [ordered]@{
  Mode = "MuMuInstallAttempt"
  Time = (Get-Date).ToString("o")
  Computer = $env:COMPUTERNAME
  User = $env:USERNAME
  InstallerPath = $InstallerPath
  InstallerArgs = $InstallerArgs
  UseScheduledTask = [bool]$UseScheduledTask
  TimeoutSeconds = $TimeoutSeconds
  LogRoot = $logRoot
  Checks = [ordered]@{}
  Errors = $errors
  Warnings = $warnings
}

try {
  if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    $errors += "Missing installer: $InstallerPath"
    throw "Missing installer"
  }

  $hash = Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256
  $report.Checks.InstallerSha256 = $hash.Hash
  $report.Checks.InitialManagers = @(Find-MuMuManager)
  $report.Checks.InitialProcesses = @(Get-MuMuProcesses)

  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $proc = $null
  $taskName = $null

  if ($UseScheduledTask) {
    if (-not $TaskPassword) {
      $errors += "TaskPassword is required when UseScheduledTask is set."
      throw "Missing TaskPassword"
    }

    $taskName = "AutoScriptorMuMuInstall_$stamp"
    $userId = "$env:COMPUTERNAME\$env:USERNAME"
    $action = New-ScheduledTaskAction -Execute $InstallerPath -Argument ($InstallerArgs -join " ")
    $principal = New-ScheduledTaskPrincipal -UserId $userId -RunLevel Highest -LogonType Password
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $task = New-ScheduledTask -Action $action -Principal $principal -Settings $settings
    Register-ScheduledTask -TaskName $taskName -InputObject $task -User $userId -Password $TaskPassword -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
    $report.Checks.ScheduledTaskName = $taskName
  } else {
    $proc = Start-Process -FilePath $InstallerPath -ArgumentList $InstallerArgs -PassThru
    $report.Checks.InstallerProcessId = $proc.Id
  }

  $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
  $lastProcesses = @()
  $managers = @()
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds ([Math]::Max(1, $PollSeconds))
    $managers = @(Find-MuMuManager)
    $lastProcesses = @(Get-MuMuProcesses)

    if ($UseScheduledTask) {
      $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
      $taskState = (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue).State
      $report.Checks.ScheduledTaskState = "$taskState"
      if ($taskInfo) {
        $report.Checks.ScheduledTaskLastTaskResult = $taskInfo.LastTaskResult
      }
      if ($managers.Count -gt 0) {
        break
      }
      if ($taskState -ne "Running" -and $lastProcesses.Count -eq 0) {
        break
      }
    } else {
      if ($proc.HasExited -and $managers.Count -gt 0) {
        break
      }

      if ($proc.HasExited -and $lastProcesses.Count -eq 0) {
        break
      }
    }
  }

  $sw.Stop()
  $report.Checks.ElapsedSeconds = [math]::Round($sw.Elapsed.TotalSeconds, 2)
  if ($UseScheduledTask) {
    $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
    $taskState = (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue).State
    $report.Checks.ScheduledTaskState = "$taskState"
    if ($taskInfo) {
      $report.Checks.ScheduledTaskLastTaskResult = $taskInfo.LastTaskResult
    }
  } else {
    $report.Checks.ProcessExited = $proc.HasExited
    $report.Checks.ExitCode = if ($proc.HasExited) { $proc.ExitCode } else { $null }
  }
  $report.Checks.MuMuManagers = $managers
  $report.Checks.MuMuProcesses = $lastProcesses
  $report.Checks.MuMuManagerFound = ($managers.Count -gt 0)

  if ((-not $UseScheduledTask) -and (-not $proc.HasExited)) {
    $warnings += "Installer process did not exit within timeout."
    if ($KillOnTimeout) {
      try {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
      } catch {}
      $warnings += "Installer process was killed after timeout."
    }
  }

  if (-not $report.Checks.MuMuManagerFound) {
    $errors += "MuMuManager.exe was not found after installer attempt."
  }
} catch {
  if (-not $errors.Count) {
    $errors += $_.Exception.Message
  }
  $report.Checks.Exception = $_.Exception.Message
} finally {
  try {
    @(Get-MuMuProcesses) | Export-Csv -NoTypeInformation -Encoding UTF8 -LiteralPath (Join-Path $logRoot "mumu-processes.csv")
  } catch {}
  if ($taskName) {
    try {
      Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue |
        Export-Clixml -LiteralPath (Join-Path $logRoot "scheduled-task.xml")
    } catch {}
  }
  $report.Errors = $errors
  $report.Warnings = $warnings
  $report.Ok = ($errors.Count -eq 0)
  Write-Json (Join-Path $logRoot "report.json") $report
  $report
}

if ($errors.Count) { exit 1 }
