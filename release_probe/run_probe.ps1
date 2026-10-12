<#
.SYNOPSIS
  框架层 wheel 的发布验收：在探针自己的 venv 里只装 dist/autoscriptor-<版本>-py3-none-any.whl，
  然后跑 release_probe 下的探针。

.DESCRIPTION
  「只利用这个 whl，不利用其他项目环境」由三件事保证：

  1. venv 建在 release_probe\.venv，只装这一个 wheel 和它的依赖（外加 CPU Paddle）；
  2. 探针进程的工作目录是 release_probe，sys.path 里只有探针目录与 venv 的 site-packages，
     探针会自己断言仓库根不在 sys.path 上；
  3. 运行数据根指向 release_probe\.runtime，不碰仓库的 data/。

.PARAMETER SkipBuild
  复用 dist/ 里已有的 wheel，不重新构建。

.PARAMETER OnlyDesktop
  只跑主机通道探针（不连模拟器、不做真机操作）。

.PARAMETER ForceReinstall
  重建探针 venv（依赖或 wheel 变了、或环境被污染时用）。
#>
[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [switch]$OnlyDesktop,
    [switch]$ForceReinstall
)

$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = 'utf-8'

$probeDir = $PSScriptRoot
$repoRoot = Split-Path -Parent $probeDir
$repoPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$venvDir = Join-Path $probeDir '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$runtimeDir = Join-Path $probeDir '.runtime'

function Write-Step([string]$text) {
    Write-Host ""
    Write-Host "==> $text" -ForegroundColor Cyan
}

function Invoke-Tool {
    <#
      跑一个外部命令并回传退出码。

      必须包一层：`$ErrorActionPreference = 'Stop'` 时 PowerShell 5.1 会把外部程序写到
      stderr 的每一行都变成终止错误（uv 的 "Using CPython ..." 就写在 stderr），
      脚本会在一条完全正常的进度输出上中断。
    #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments)][string[]]$Arguments
    )
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'      # 只在这一句调用期间放开，调用方仍按退出码判成败
    try {
        & $FilePath @Arguments 2>&1 | ForEach-Object { Write-Host "    $_" }
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

if (-not (Test-Path $repoPython)) {
    throw "找不到仓库 venv：$repoPython。先跑 .\scripts\install.bat python。"
}

if (-not $SkipBuild) {
    Write-Step "构建 wheel"
    Push-Location $repoRoot
    try {
        $code = Invoke-Tool $repoPython -X utf8 scripts\build_wheels.py
        if ($code -ne 0) { throw "构建 wheel 失败（退出码 $code）" }
    }
    finally {
        Pop-Location
    }
}

Write-Step "解析 wheel 版本"
$version = (& $repoPython -X utf8 -c "import sys; sys.path.insert(0, r'$repoRoot'); from scripts import build_wheels; print(build_wheels.read_project_version())" 2>$null | Select-Object -Last 1)
$version = "$version".Trim()
if (-not $version) { throw "读不到 pyproject.toml 里的版本号" }
$wheelPath = Join-Path $repoRoot "dist\autoscriptor-$version-py3-none-any.whl"
if (-not (Test-Path $wheelPath)) { throw "找不到 wheel：$wheelPath（去掉 -SkipBuild 重新构建）" }
Write-Host "    wheel = $wheelPath"

if ($ForceReinstall -and (Test-Path $venvDir)) {
    Write-Step "重建探针 venv"
    Remove-Item -Recurse -Force $venvDir
}

if (-not (Test-Path $venvPython)) {
    Write-Step "创建探针 venv（release_probe\.venv）"
    $code = Invoke-Tool uv venv --python 3.10.15 $venvDir
    if ($code -ne 0) { throw "创建 venv 失败（退出码 $code）" }
}

Write-Step "安装 wheel（只装这一个 whl 及其依赖）"
# --reinstall-package：版本号不变时（改了源码重新打包）uv 会认为已装好而跳过，装上的是
# 旧代码。只重装这一个包，不连带动其它 97 个依赖。
$code = Invoke-Tool uv pip install --reinstall-package autoscriptor --python $venvPython $wheelPath
if ($code -ne 0) { throw "安装 wheel 失败（退出码 $code）" }

Write-Step "安装 OCR 运行时（CPU Paddle）"
$code = Invoke-Tool uv pip install --python $venvPython -r (Join-Path $probeDir 'requirements.txt')
if ($code -ne 0) { throw "安装 Paddle 失败（退出码 $code）" }

$env:AUTOSCRIPTOR_DATA_DIR = $runtimeDir
$env:PROBE_EVIDENCE_DIR = Join-Path $runtimeDir 'evidence'
New-Item -ItemType Directory -Force -Path $env:PROBE_EVIDENCE_DIR | Out-Null

Push-Location $probeDir
try {
    $results = @()

    Write-Step "主机通道探针"
    $code = Invoke-Tool $venvPython -X utf8 probe_desktop.py
    $results += [pscustomobject]@{ Probe = 'desktop'; ExitCode = $code }

    if (-not $OnlyDesktop) {
        Write-Step "框架层探针（真机：点击 / 识别 / 4399 部分操作）"
        $code = Invoke-Tool $venvPython -X utf8 probe_framework.py
        $results += [pscustomobject]@{ Probe = 'framework'; ExitCode = $code }
    }
}
finally {
    Pop-Location
}

Write-Step "结论"
$results | ForEach-Object {
    $label = if ($_.ExitCode -eq 0) { '通过' } else { '未通过' }
    Write-Host ("    {0,-10} {1}（退出码 {2}）" -f $_.Probe, $label, $_.ExitCode)
}
Write-Host "    数据根：$runtimeDir"
Write-Host "    证据图：$env:PROBE_EVIDENCE_DIR"

$failed = @($results | Where-Object { $_.ExitCode -ne 0 })
if ($failed.Count -gt 0) {
    throw "发布验收未通过：$($failed.Probe -join ', ')"
}
