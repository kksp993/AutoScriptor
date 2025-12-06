# --------------------------------------------------------------------------------
# PowerShell (.ps1) script
# Purpose: Start AutoScriptor installer, logic is the same as the original .bat script.
# --------------------------------------------------------------------------------

# PowerShell will automatically stop at the first error, equivalent to the implicit behavior of batch
$ErrorActionPreference = "Stop"

# 1. Normalize to repository root directory (current file is located in AutoScriptor\installer)
# $PSScriptRoot 是一个自动变量，表示当前脚本所在的目录
$ScriptDir = $PSScriptRoot
# Parse the absolute path of the project root directory
$Root = Resolve-Path -Path (Join-Path $ScriptDir ".")

# 2. Use existing .venv if exists, otherwise create it by installer
# Use Join-Path to reliably build the path
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"

# 3. Select target (default webui, can pass webui/cli/install-only)
# $args is an array containing all command line arguments
if ($args.Count -gt 0) {
    $Target = $args[0]
} else {
    $Target = "webui"
}

# Define the path of the Python script to execute
$InstallerScript = Join-Path $Root "services\installer\installer.py"

# 4. If venv exists, use venv python; otherwise ensure Python 3.10 is available or bootstrap-install it
if (Test-Path -Path $VenvPy -PathType Leaf) {
    Write-Host "Detect venv, use venv python to run installer..."
    & $VenvPy $InstallerScript @args
} else {
    Write-Host "No venv detected, searching for Python 3.10..."

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        # Test whether `py -3.10` is available
        & $pyLauncher.Source -3.10 -c "import sys" *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Found Python via 'py -3.10'."
            & $pyLauncher.Source -3.10 $InstallerScript @args
            exit $LASTEXITCODE
        }
    }

    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $pyCmd) {
        $verOut = & $pyCmd.Source --version 2>&1
        if ($verOut -match "Python 3\.10\.") {
            Write-Host "Found 'python' 3.10.x."
            & $pyCmd.Source $InstallerScript @args
            exit $LASTEXITCODE
        }
    }

    Write-Host "Python 3.10 not found. Bootstrap installing Python 3.10 locally..."

    # Download official installer to repository cache if missing
    $PyVersion = "3.10.11"
    $CacheDir = Join-Path $Root "wheelhouse\python"
    $InstallerFile = "python-$PyVersion-amd64.exe"
    $PyUrl = "https://www.python.org/ftp/python/$PyVersion/$InstallerFile"
    if ($env:AUTOSCRIPTOR_PYTHON_URL) {
        $PyUrl = $env:AUTOSCRIPTOR_PYTHON_URL
        $InstallerFile = Split-Path -Path $PyUrl -Leaf
    }
    $InstallerPath = Join-Path $CacheDir $InstallerFile

    if (-not (Test-Path -Path $CacheDir -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
    }
    $usedCached = $false
    if (-not (Test-Path -Path $InstallerPath -PathType Leaf)) {
        Write-Host "Downloading Python $PyVersion ..." 
        Invoke-WebRequest -Uri $PyUrl -OutFile $InstallerPath -UseBasicParsing
    } else {
        $usedCached = $true
        Write-Host "Using cached installer: $InstallerPath"
    }

    # Install per-user into repository-local directory to avoid admin requirements
    $RepoPyDir = Join-Path $Root ".python310"
    if (-not (Test-Path -Path $RepoPyDir -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $RepoPyDir | Out-Null
    }

    $silentArgs = @(
        "/quiet",
        "SimpleInstall=1",
        "InstallAllUsers=0",
        "Include_pip=1",
        "Include_launcher=1",
        "PrependPath=0",
        "Shortcuts=0",
        "Include_test=0",
        "TargetDir=$RepoPyDir"
    )

    Write-Host "Installing Python $PyVersion into $RepoPyDir ..."
    $proc = Start-Process -FilePath $InstallerPath -ArgumentList $silentArgs -Wait -PassThru
    if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne 3010) {
        Write-Warning "Python 3.10 安装失败（退出码: $($proc.ExitCode)）。尝试重新下载安装器并重试..."
        try { Remove-Item -Force -ErrorAction SilentlyContinue $InstallerPath } catch {}
        Write-Host "Re-downloading Python $PyVersion ..."
        Invoke-WebRequest -Uri $PyUrl -OutFile $InstallerPath -UseBasicParsing
        $proc = Start-Process -FilePath $InstallerPath -ArgumentList $silentArgs -Wait -PassThru
        if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne 3010) {
            Write-Error "Python 3.10 安装失败，退出码: $($proc.ExitCode)"
            exit $proc.ExitCode
        }
    }

    $RepoPyExe = Join-Path $RepoPyDir "python.exe"
    if (-not (Test-Path -Path $RepoPyExe -PathType Leaf)) {
        Write-Error "未找到安装后的 python.exe: $RepoPyExe"
        exit 1
    }

    Write-Host "Python 3.10 installed. Launching installer with local Python..."
    & $RepoPyExe $InstallerScript @args
    exit $LASTEXITCODE
}

# Exit script and pass the exit code of the python script
# $LASTEXITCODE is an automatic variable, saving the exit code of the last external program run
exit $LASTEXITCODE