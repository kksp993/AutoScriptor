param(
    [Parameter(Mandatory = $false)]
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,

    [Parameter(Mandatory = $false)]
    [string]$PythonVersion = "3.10.15"
)

$ErrorActionPreference = "Stop"

function Resolve-Uv {
    $cmd = Get-Command "uv.exe" -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        $cmd = Get-Command "uv" -ErrorAction SilentlyContinue
    }
    if ($null -eq $cmd) {
        throw "uv not found. Run scripts\install.bat tools first."
    }
    return $cmd.Source
}

$uv = Resolve-Uv
Write-Host "Ensuring uv-managed Python $PythonVersion is available ..."
& $uv python install $PythonVersion
if ($LASTEXITCODE -ne 0) {
    throw "uv python install $PythonVersion failed with exit code $LASTEXITCODE"
}

Write-Host "Python $PythonVersion ready for uv venv"
exit 0
