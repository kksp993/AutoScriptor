param(
    [ValidateSet("tools", "python", "electron", "all")]
    [string]$Target = "all"
)

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
$Root = (Resolve-Path -Path (Join-Path $ScriptDir "..")).Path
$VenvDir = Join-Path $Root ".venv"
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"
$Requirements = Join-Path $Root "requirements.txt"
$WebappDir = Join-Path $Root "webapp"
$PythonVersion = "3.10.15"
$NodeMinimumVersion = [version]"22.12.0"

function Refresh-ProcessPath {
    $pathValues = @(
        [Environment]::GetEnvironmentVariable("Path", "Machine"),
        [Environment]::GetEnvironmentVariable("Path", "User"),
        $env:Path,
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Launcher"),
        (Join-Path $env:USERPROFILE ".local\bin"),
        (Join-Path $env:ProgramFiles "Git\cmd"),
        (Join-Path $env:ProgramFiles "nodejs")
    )
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $paths = foreach ($value in $pathValues) {
        foreach ($entry in ($value -split ";")) {
            $entry = $entry.Trim()
            if ($entry -and $seen.Add($entry)) { $entry }
        }
    }

    $env:Path = ($paths -join ";")
}

function Resolve-CommandPath {
    param([string[]]$Names)

    Refresh-ProcessPath
    foreach ($name in $Names) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $cmd) {
            return $cmd.Source
        }
    }
    return $null
}

function Require-Winget {
    $winget = Resolve-CommandPath @("winget.exe", "winget")
    if (-not $winget) {
        throw "winget not found. Install App Installer from Microsoft Store, reopen PowerShell, then rerun scripts\install.bat."
    }
    return $winget
}

function Invoke-WingetInstall {
    param(
        [string]$Id,
        [string]$Name
    )

    $winget = Require-Winget
    Write-Host "Installing $Name with winget package $Id ..."
    & $winget install --id $Id -e --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget install failed for $Id with exit code $LASTEXITCODE"
    }
    Refresh-ProcessPath
}

function Ensure-ExecutionPolicy {
    Write-Host "Setting CurrentUser PowerShell execution policy to RemoteSigned ..."
    $processPolicy = $env:PSExecutionPolicyPreference
    if ($processPolicy) {
        Remove-Item Env:\PSExecutionPolicyPreference -ErrorAction SilentlyContinue
    }
    try {
        Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
    } finally {
        if ($processPolicy) {
            $env:PSExecutionPolicyPreference = $processPolicy
        }
    }

    $policy = Get-ExecutionPolicy -Scope CurrentUser
    if ($policy -ne "RemoteSigned") {
        throw "Failed to set CurrentUser execution policy to RemoteSigned. CurrentUser is $policy."
    }
}

function Ensure-Git {
    $git = Resolve-CommandPath @("git.exe", "git")
    if (-not $git) {
        Invoke-WingetInstall -Id "Git.Git" -Name "Git for Windows"
        $git = Resolve-CommandPath @("git.exe", "git")
    }
    if (-not $git) {
        throw "Git was installed but git.exe is still not visible in PATH. Reopen PowerShell and rerun scripts\install.bat."
    }
    Write-Host "Git ready: $(& $git --version)"
}

function Get-NodeVersion {
    $node = Resolve-CommandPath @("node.exe", "node")
    if (-not $node) {
        return $null
    }

    $raw = (& $node -v).Trim()
    if ($LASTEXITCODE -ne 0 -or $raw -notmatch "^v?(\d+\.\d+\.\d+)") {
        return $null
    }
    return [version]$Matches[1]
}

function Ensure-Node {
    $version = Get-NodeVersion
    $npm = Resolve-CommandPath @("npm.cmd", "npm")
    if ($version -and $version -ge $NodeMinimumVersion -and $npm) {
        Write-Host "Node ready: v$version"
        Write-Host "npm ready: $(& $npm -v)"
        return
    }

    Invoke-WingetInstall -Id "OpenJS.NodeJS.LTS" -Name "Node.js LTS"

    $version = Get-NodeVersion
    $npm = Resolve-CommandPath @("npm.cmd", "npm")
    if (-not $version -or $version -lt $NodeMinimumVersion) {
        throw "Node.js >= $NodeMinimumVersion is required. Reopen PowerShell and rerun scripts\install.bat."
    }
    if (-not $npm) {
        throw "npm was not found after Node.js install. Reopen PowerShell and rerun scripts\install.bat."
    }
    Write-Host "Node ready: v$version"
    Write-Host "npm ready: $(& $npm -v)"
}

function Ensure-Uv {
    $uv = Resolve-CommandPath @("uv.exe", "uv")
    if (-not $uv) {
        Invoke-WingetInstall -Id "astral-sh.uv" -Name "uv"
        $uv = Resolve-CommandPath @("uv.exe", "uv")
    }
    if (-not $uv) {
        throw "uv was installed but uv.exe is still not visible in PATH. Reopen PowerShell and rerun scripts\install.bat."
    }
    Write-Host "uv ready: $(& $uv --version)"
    return $uv
}

function Install-Tools {
    Ensure-ExecutionPolicy
    Ensure-Git
    Ensure-Node
    Ensure-Uv | Out-Null
}

function Test-VenvPython {
    if (-not (Test-Path -LiteralPath $VenvPy -PathType Leaf)) {
        return $false
    }

    $version = & $VenvPy -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
    return $LASTEXITCODE -eq 0 -and $version.Trim() -eq $PythonVersion
}

function Ensure-Venv {
    $uv = Ensure-Uv

    if (Test-Path -LiteralPath $VenvDir -PathType Container) {
        if (Test-VenvPython) {
            Write-Host ".venv already uses Python $PythonVersion"
            return
        }
        throw ".venv exists but is not Python $PythonVersion. Remove .venv and rerun scripts\install.bat python."
    }

    $BootstrapScript = Join-Path $Root "scripts\bootstrap-python310.ps1"
    & $BootstrapScript -Root $Root -PythonVersion $PythonVersion
    if ($LASTEXITCODE -ne 0) {
        throw "Python $PythonVersion bootstrap failed with exit code $LASTEXITCODE"
    }

    Write-Host "Creating source virtual environment with uv venv --python $PythonVersion ..."
    & $uv venv --python $PythonVersion $VenvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-VenvPython)) {
        throw "Failed to create .venv with Python $PythonVersion"
    }
}

function Install-PythonDeps {
    if (-not (Test-Path -LiteralPath $Requirements -PathType Leaf)) {
        throw "Missing requirements file: $Requirements"
    }

    Ensure-Venv

    $uv = Ensure-Uv
    Write-Host "Installing Python dependencies from requirements.txt with uv pip install ..."
    & $uv pip install --python $VenvPy -r $Requirements
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency installation failed with exit code $LASTEXITCODE"
    }
}

function Install-ElectronDeps {
    if (-not (Test-Path -LiteralPath (Join-Path $WebappDir "package.json") -PathType Leaf)) {
        throw "Missing Electron package.json: $WebappDir"
    }

    Ensure-Node
    $npm = Resolve-CommandPath @("npm.cmd", "npm")

    Write-Host "Installing Electron dependencies in webapp with npm install ..."
    Push-Location $WebappDir
    try {
        & $npm install
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }

    $electronPackage = Join-Path $WebappDir "node_modules\electron\package.json"
    if (-not (Test-Path -LiteralPath $electronPackage -PathType Leaf)) {
        throw "Electron dependency is missing after npm install: $electronPackage"
    }
}

if ($Target -eq "tools" -or $Target -eq "all") {
    Install-Tools
}

if ($Target -eq "python" -or $Target -eq "all") {
    Install-PythonDeps
}

if ($Target -eq "electron" -or $Target -eq "all") {
    Install-ElectronDeps
}

Write-Host "Install complete: $Target"
exit 0
