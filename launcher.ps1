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
$InstallerScript = Join-Path $Root "AutoScriptor\installer\installer.py"

# 4. If venv exists, use venv to run installer; otherwise try to use system python, created by installer
if (Test-Path -Path $VenvPy -PathType Leaf) {
    # If python.exe exists in venv
    Write-Host "Detect venv, use venv python to run installer..."
    # Use '&' (call operator) to execute commands containing spaces or variables
    & $VenvPy $InstallerScript $Target
} else {
    # If venv does not exist, try to use system python
    Write-Host "No venv detected, try to use system python..."
    # Get-Command can safely check if the command exists, more reliable than 'where.exe'
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        # If 'py.exe' exists
        Write-Host "Detect 'py.exe' launcher, use 'py -3' to run..."
        py -3 $InstallerScript $Target
    } else {
        # If 'py.exe' does not exist, fallback to 'python'
        Write-Host "No 'py.exe' detected, fallback to 'python'..."
        python $InstallerScript $Target
    }
}

# Exit script and pass the exit code of the python script
# $LASTEXITCODE is an automatic variable, saving the exit code of the last external program run
exit $LASTEXITCODE