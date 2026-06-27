param(
    [ValidateSet("webui", "electron")]
    [string]$Target = "webui",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AppArgs
)

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
$Root = (Resolve-Path -Path (Join-Path $ScriptDir "..")).Path
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$GuiScript = Join-Path $Root "services\webui\gui.py"
$WebappDir = Join-Path $Root "webapp"

function Require-File {
    param(
        [string]$Path,
        [string]$Message
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw $Message
    }
}

function Find-Npm {
    $names = @("npm.cmd", "npm")
    foreach ($name in $names) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $cmd) {
            return $cmd.Source
        }
    }
    return $null
}

Require-File $VenvPy "Missing .venv Python. Run scripts\install.bat first."

if ($Target -eq "webui") {
    Require-File $GuiScript "Missing source entry: $GuiScript"
    Write-Host "Starting AutoScriptor WebUI from source..."
    & $VenvPy -X utf8 $GuiScript @AppArgs
    exit $LASTEXITCODE
}

$npm = Find-Npm
if (-not $npm) {
    throw "npm not found. Run scripts\install.bat electron first."
}

Require-File (Join-Path $WebappDir "node_modules\electron\package.json") "Missing Electron dependencies. Run scripts\install.bat electron first; it runs npm install in webapp."

Write-Host "Starting AutoScriptor Electron from source..."
Push-Location $WebappDir
try {
    & $npm start
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
