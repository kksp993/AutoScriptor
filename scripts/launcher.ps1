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

    # Check local .python310 first (embeddable zip extracted by bootstrap)
    $LocalPy310 = Join-Path $Root ".python310\python.exe"
    if (Test-Path -Path $LocalPy310 -PathType Leaf) {
        Write-Host "Found local Python 3.10 at $LocalPy310"
        & $LocalPy310 $InstallerScript @args
        exit $LASTEXITCODE
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
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

    Write-Host "Python 3.10 not found. Bootstrap installing Python 3.10.11 locally..."

    $BootstrapScript = Join-Path $Root "scripts\bootstrap-python310.ps1"
    & $BootstrapScript -Root $Root
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Python 3.10 bootstrap failed with exit code $LASTEXITCODE"
        exit $LASTEXITCODE
    }

    $RepoPyExe = Join-Path $Root ".python310\python.exe"
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