param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AppArgs
)

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
$Root = (Resolve-Path -Path (Join-Path $ScriptDir "..")).Path
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$Runner = Join-Path $Root "test\manual_safety_education.py"

function Require-File {
    param(
        [string]$Path,
        [string]$Message
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw $Message
    }
}

Require-File $VenvPy "Missing .venv Python. Run scripts\install.bat first."
Require-File $Runner "Missing safety education runner: $Runner"

Write-Host "Starting standalone safety education runner..."
& $VenvPy -X utf8 $Runner @AppArgs
exit $LASTEXITCODE
