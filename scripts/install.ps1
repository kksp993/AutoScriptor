param(
    [ValidateSet("tools", "python", "electron", "all")]
    [string]$Target = "all",

    [ValidateSet("auto", "cpu", "gpu")]
    [string]$PaddleVariant = "auto"
)

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
$Root = (Resolve-Path -Path (Join-Path $ScriptDir "..")).Path
$VenvDir = Join-Path $Root ".venv"
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"
$CommonRequirements = Join-Path $Root "requirements.txt"
$CpuRequirements = Join-Path $Root "requirements-cpu.txt"
$GpuRequirements = Join-Path $Root "requirements-gpu.txt"
$RuntimeConfig = Join-Path $Root "data\config.json"
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

function Resolve-PaddleVariant {
    if ($PaddleVariant -ne "auto") {
        return $PaddleVariant
    }

    if (-not (Test-Path -LiteralPath $RuntimeConfig -PathType Leaf)) {
        Write-Host "data\config.json is absent; selecting the CPU Paddle runtime."
        return "cpu"
    }

    try {
        $configDocument = Get-Content -Raw -Encoding UTF8 -LiteralPath $RuntimeConfig | ConvertFrom-Json
    } catch {
        throw "Failed to read Paddle variant from $RuntimeConfig`: $($_.Exception.Message)"
    }

    $configuredUseGpu = $false
    if ($null -ne $configDocument.ocr -and $null -ne $configDocument.ocr.use_gpu) {
        $configuredUseGpu = [bool]$configDocument.ocr.use_gpu
    }

    if ($configuredUseGpu) {
        return "gpu"
    }
    return "cpu"
}

function Test-PaddleRuntime {
    param([ValidateSet("cpu", "gpu")][string]$SelectedVariant)

    $expectedCudaLiteral = if ($SelectedVariant -eq "gpu") { "True" } else { "False" }
    $probe = "import paddle; expected_cuda = $expectedCudaLiteral; actual_cuda = paddle.device.is_compiled_with_cuda(); gpu_count = paddle.device.cuda.device_count(); print(f'paddle={paddle.__version__}, cuda_compiled={actual_cuda}, gpu_count={gpu_count}'); assert actual_cuda == expected_cuda, f'expected CUDA compiled={expected_cuda}, got {actual_cuda}'; assert not expected_cuda or gpu_count > 0, 'GPU Paddle is installed but no CUDA device is available'"
    & $VenvPy -X utf8 -c $probe
    if ($LASTEXITCODE -ne 0) {
        throw "Paddle $SelectedVariant runtime validation failed with exit code $LASTEXITCODE"
    }
}

function Install-PythonDeps {
    $selectedPaddleVariant = Resolve-PaddleVariant
    $variantRequirements = if ($selectedPaddleVariant -eq "gpu") { $GpuRequirements } else { $CpuRequirements }

    foreach ($requirementsPath in @($CommonRequirements, $variantRequirements)) {
        if (-not (Test-Path -LiteralPath $requirementsPath -PathType Leaf)) {
            throw "Missing requirements file: $requirementsPath"
        }
    }

    Ensure-Venv

    $uv = Ensure-Uv
    Write-Host "Installing common Python dependencies from requirements.txt ..."
    & $uv pip install --python $VenvPy -r $CommonRequirements
    if ($LASTEXITCODE -ne 0) {
        throw "Common Python dependency installation failed with exit code $LASTEXITCODE"
    }

    Write-Host "Removing mutually exclusive Paddle CPU/GPU packages before selecting $selectedPaddleVariant ..."
    & $uv pip uninstall --python $VenvPy paddlepaddle paddlepaddle-gpu
    if ($LASTEXITCODE -ne 0) {
        throw "Existing Paddle package removal failed with exit code $LASTEXITCODE"
    }

    $variantFileName = Split-Path -Leaf $variantRequirements
    Write-Host "Installing Paddle $selectedPaddleVariant runtime from $variantFileName ..."
    & $uv pip install --python $VenvPy -r $variantRequirements
    if ($LASTEXITCODE -ne 0) {
        throw "Paddle $selectedPaddleVariant installation failed with exit code $LASTEXITCODE"
    }

    Test-PaddleRuntime -SelectedVariant $selectedPaddleVariant
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

Write-Host "Install complete: target=$Target, paddle=$PaddleVariant"
exit 0
