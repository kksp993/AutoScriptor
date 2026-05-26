# 下载 Python 3.10.11 embeddable zip 并解压到仓库 .python310（纯解压，不碰注册表，不受 Anaconda 干扰）
# 然后启用 site-packages 并安装 pip，使其可用于创建 venv 和安装依赖。
param(
    [Parameter(Mandatory = $false)]
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)
$ErrorActionPreference = "Stop"

$PyVersion   = "3.10.11"
$RepoPyDir   = Join-Path $Root ".python310"
$RepoPyExe   = Join-Path $RepoPyDir "python.exe"

if (Test-Path -Path $RepoPyExe -PathType Leaf) {
    Write-Host "Local Python 3.10 already present: $RepoPyExe"
    exit 0
}

$CacheDir = Join-Path $Root "wheelhouse\python"
if (-not (Test-Path $CacheDir)) { New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null }

# ── 1. 下载 embeddable zip ──────────────────────────────────────────────────
$ZipName = "python-$PyVersion-embed-amd64.zip"
$ZipUrl  = "https://www.python.org/ftp/python/$PyVersion/$ZipName"
if ($env:AUTOSCRIPTOR_PYTHON_URL) {
    $ZipUrl  = $env:AUTOSCRIPTOR_PYTHON_URL
    $ZipName = Split-Path -Path $ZipUrl -Leaf
}
$ZipPath = Join-Path $CacheDir $ZipName

$FreshInstall = $env:AUTOSCRIPTOR_FRESH_INSTALL -match '^(1|true|yes|on)$'
if ($FreshInstall -and (Test-Path $ZipPath)) {
    Write-Host "AUTOSCRIPTOR_FRESH_INSTALL: removing cached zip"
    Remove-Item -Force $ZipPath
}
if (-not (Test-Path $ZipPath)) {
    Write-Host "Downloading Python $PyVersion embeddable zip ..."
    Invoke-WebRequest -Uri $ZipUrl -OutFile $ZipPath -UseBasicParsing
} else {
    Write-Host "Using cached zip: $ZipPath"
}

# ── 2. 解压 ─────────────────────────────────────────────────────────────────
if (Test-Path $RepoPyDir) { Remove-Item -Recurse -Force $RepoPyDir }
Write-Host "Extracting to $RepoPyDir ..."
Expand-Archive -Path $ZipPath -DestinationPath $RepoPyDir -Force

if (-not (Test-Path $RepoPyExe -PathType Leaf)) {
    Write-Error "python.exe not found after extraction: $RepoPyExe"
    exit 1
}

# ── 3. 启用 import site（解开 ._pth 文件里的 #import site） ─────────────────
$pthFile = Get-ChildItem -Path $RepoPyDir -Filter "python*._pth" | Select-Object -First 1
if ($null -ne $pthFile) {
    $content = Get-Content $pthFile.FullName -Raw
    $content = $content.Replace('#import site', 'import site')
    Set-Content -Path $pthFile.FullName -Value $content -NoNewline
    Write-Host "Enabled 'import site' in $($pthFile.Name)"
}

# ── 4. 安装 pip（embeddable zip 默认不含 pip） ──────────────────────────────
$getPipLocal = Join-Path $Root "services\installer\get-pip.py"
$getPipCache = Join-Path $CacheDir "get-pip.py"
if (Test-Path $getPipLocal) {
    $getPip = $getPipLocal
} elseif (Test-Path $getPipCache) {
    $getPip = $getPipCache
} else {
    Write-Host "Downloading get-pip.py ..."
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPipCache -UseBasicParsing
    $getPip = $getPipCache
}

Write-Host "Installing pip ..."
& $RepoPyExe $getPip --no-warn-script-location
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install pip (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

# ── 5. 安装 virtualenv + tkinter（embeddable zip 缺少 venv 和 tkinter） ───────
Write-Host "Installing virtualenv and tkinter-embed ..."
& $RepoPyExe -m pip install virtualenv tkinter-embed --no-warn-script-location

Write-Host "Python $PyVersion ready at $RepoPyExe"
exit 0
