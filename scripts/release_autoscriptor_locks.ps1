#Requires -Version 5.1
<#
.SYNOPSIS
  释放造笔开发/安装目录占用：结束监听 5000 端口的进程，以及「可执行文件路径位于本仓库下」的进程（含 backend 引擎）。

.PARAMETER ProjectRoot
  仓库根目录，默认为本脚本所在目录的上一级（…\AutoScriptor）。
#>
param(
  [string]$ProjectRoot = ""
)

$ErrorActionPreference = 'SilentlyContinue'
if (-not $ProjectRoot) {
  $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}
$prefix = $ProjectRoot.TrimEnd('\') + '\'
Write-Host "[release] repo root: $prefix" -ForegroundColor Cyan

# Port 5000 (WebUI)
$pids5000 = [System.Collections.Generic.HashSet[int]]::new()
try {
  Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction Stop | ForEach-Object {
    if ($_.OwningProcess -gt 0) { [void]$pids5000.Add($_.OwningProcess) }
  }
} catch {
  $netstat = netstat -ano 2>$null
  foreach ($line in $netstat) {
    if ($line -match ':5000\s' -and $line -match 'LISTENING') {
      $parts = $line.Trim() -split '\s+'
      $listenPid = [int]$parts[-1]
      if ($listenPid -gt 0) { [void]$pids5000.Add($listenPid) }
    }
  }
}
foreach ($portPid in $pids5000) {
  try {
    $p = Get-Process -Id $portPid -ErrorAction Stop
    Write-Host "[release] kill port 5000 PID=$portPid ($($p.ProcessName))" -ForegroundColor Yellow
    Stop-Process -Id $portPid -Force -ErrorAction Stop
  } catch {}
}

# Processes whose exe path is under repo (includes backend)
$killed = 0
Get-CimInstance Win32_Process | ForEach-Object {
  $exe = $_.ExecutablePath
  if (-not $exe) { return }
  if (-not $exe.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) { return }
  if ($_.ProcessId -eq $PID) { return }
  try {
    Write-Host "[release] kill PID=$($_.ProcessId) $exe" -ForegroundColor Yellow
    Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
    $killed++
  } catch {}
}

Write-Host "[release] done. killed_under_repo=$killed. If EPERM persists, exclude folder in AV or use another install path." -ForegroundColor Green
