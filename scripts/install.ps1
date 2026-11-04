param(
    [ValidateSet("tools", "python", "electron", "qq", "all")]
    [string]$Target = "all",

    [ValidateSet("auto", "cpu", "gpu")]
    [string]$PaddleVariant = "auto",

    [switch]$WithQQ,

    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

# 这个脚本的目标是「用户只要会双击就能装完」。所以：
#   - 每一步都先说明正在做什么；
#   - 任何失败都给出「哪一步 / 为什么 / 你可以怎么做 / 等价命令」；
#   - 全过程写进日志文件，用户可以直接把这份日志发出来。

$script:CurrentStep = "准备"
$script:CurrentHints = @()

function Write-Head {
    param([string]$Message)
    Write-Host 
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Set-Step {
    param([string]$Name, [string[]]$Hints)
    $script:CurrentStep = $Name
    $script:CurrentHints = $Hints
    Write-Head $Name
}

function Fail-Install {
    param(
        [string]$Step,
        [string]$Reason,
        [string[]]$Actions,
        [string]$ManualCommand
    )
    Write-Host ""
    Write-Host "================ 安装没有完成 ================" -ForegroundColor Red
    Write-Host "  哪一步：$Step"
    Write-Host "  为什么：$Reason"
    if ($ManualCommand) {
        Write-Host ""
        Write-Host "  手动做等价的事：" -ForegroundColor Yellow
        Write-Host "    $ManualCommand" -ForegroundColor Yellow
    }
    if ($Actions -and $Actions.Count -gt 0) {
        Write-Host ""
        Write-Host "  你可以这样做："
        $index = 1
        foreach ($action in $Actions) {
            Write-Host "    $index) $action"
            $index++
        }
    }
    Write-Host ""
    Write-Host "  完整输出已保存在：$InstallLogPath"
    Write-Host "  照着上面做完，再运行一次 .\scripts\install.bat 即可。" -ForegroundColor Green
    Write-Host "=============================================" -ForegroundColor Red
    exit 1
}

function Initialize-InstallLog {
    # transcript 让用户能直接发一份完整输出；失败不影响安装。
    try {
        $logDir = Join-Path $Root logs
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $script:InstallLogPath = Join-Path $logDir "install_$stamp.log"
        Start-Transcript -Path $script:InstallLogPath -Force | Out-Null
    } catch {
        $script:InstallLogPath = "(没有生成日志文件)"
    }
}

$ScriptDir = $PSScriptRoot
$Root = (Resolve-Path -Path (Join-Path $ScriptDir "..")).Path
$VenvDir = Join-Path $Root ".venv"
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"
$CommonRequirements = Join-Path $Root "requirements.txt"
$CpuRequirements = Join-Path $Root "requirements-cpu.txt"
$GpuRequirements = Join-Path $Root "requirements-gpu.txt"
$RuntimeConfig = Join-Path $Root "data\config.json"
$ElectronDir = Join-Path $Root "frontend\electron"
$PythonVersion = "3.10.15"
$NodeMinimumVersion = [version]"22.12.0"
$VisualCppMinimumVersion = [version]"14.40.0.0"
$SetuptoolsUpperBound = "81"
$SetuptoolsRequirement = "setuptools<$SetuptoolsUpperBound"
# Set by Install-PythonDeps so the completion line reports the variant that was
# actually installed, not the "auto" default the user typed.
$ResolvedPaddleVariant = $null

Initialize-InstallLog

function Test-InstallPrerequisites {
    Set-Step "检查系统与源码目录" @(
        "需要 Windows 10/11 x64 和 64 位 PowerShell 5.1 或更高版本",
        "请先完整解压源码到当前用户可写的本地目录，不要在压缩包内直接运行"
    )
    $architecture = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    if ($architecture -ne "AMD64" -or -not [Environment]::Is64BitProcess -or
        [Environment]::OSVersion.Version.Build -lt 17763 -or $PSVersionTable.PSVersion -lt [version]"5.1") {
        throw "Unsupported system. Windows 10 build 17763+ / Windows 11 x64 and 64-bit PowerShell 5.1+ are required."
    }

    foreach ($relativePath in @("requirements.txt", "requirements-cpu.txt", "requirements-gpu.txt", "data\config.template.json", "backend\webui\gui.py", "frontend\electron\package.json")) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $relativePath) -PathType Leaf)) {
            throw "Incomplete source tree: missing $relativePath"
        }
    }
    $writeProbe = Join-Path $Root (".install-write-" + [Guid]::NewGuid().ToString("N"))
    try {
        [System.IO.File]::WriteAllText($writeProbe, "")
    } finally {
        if (Test-Path -LiteralPath $writeProbe) { Remove-Item -LiteralPath $writeProbe -Force }
    }
}

function Refresh-ProcessPath {
    # 用户把工具装在哪儿都可能：winget、官网安装包、Scoop、Chocolatey、nvm、fnm、
    # 以及「只为当前用户安装」。注册表里的 PATH 已经覆盖大部分情况，这里再补上
    # 各家用默认路径，避免出现「明明装了却找不到」。
    $pathValues = @(
        [Environment]::GetEnvironmentVariable("Path", "Machine"),
        [Environment]::GetEnvironmentVariable("Path", "User"),
        $env:Path,
        (Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Launcher"),
        (Join-Path $env:USERPROFILE ".local\bin"),
        (Join-Path $env:ProgramFiles "Git\cmd"),
        (Join-Path $env:ProgramFiles "nodejs"),
        # Git：官网安装包在 64 位系统上也可能是 Program Files (x86)
        (Join-Path ${env:ProgramFiles(x86)} "Git\cmd"),
        # Git / Node 的「仅当前用户」安装
        (Join-Path $env:LOCALAPPDATA "Programs\Git\cmd"),
        (Join-Path $env:LOCALAPPDATA "Programs\nodejs"),
        # npm 全局 bin（有些工具只装在这里）
        (Join-Path $env:APPDATA "npm"),
        # Scoop / Chocolatey
        (Join-Path $env:USERPROFILE "scoop\shims"),
        (Join-Path $env:ProgramData "chocolatey\bin"),
        # nvm-windows 的当前软链、fnm 的 shims
        (Join-Path $env:APPDATA "nvm"),
        (Join-Path $env:LOCALAPPDATA "fnm_multishells"),
        (Join-Path $env:LOCALAPPDATA "Volta\bin")
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
        $cmd = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $cmd) {
            return $cmd.Source
        }
    }
    return $null
}

function Require-Winget {
    $winget = Resolve-CommandPath @("winget.exe", "winget")
    if (-not $winget) {
        Set-Step "准备 winget（应用安装程序）" @(
            "正在使用微软官方 Microsoft.WinGet.Client 模块为当前用户安装 winget",
            "若网络或组织策略阻止安装，请在 Microsoft Store 安装「应用安装程序」，再重试",
            "系统可能弹出权限确认；拒绝授权时安装会停止，不会绕过组织策略"
        )
        # Fresh Windows PowerShell may negotiate TLS 1.0 with PSGallery.
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Install-PackageProvider -Name NuGet -Scope CurrentUser -Force | Out-Null
        Install-Module -Name Microsoft.WinGet.Client -Repository PSGallery -Scope CurrentUser -Force | Out-Null
        Import-Module Microsoft.WinGet.Client
        Repair-WinGetPackageManager | Out-Null
        $winget = Resolve-CommandPath @("winget.exe", "winget")
    }
    if (-not $winget) {
        throw "winget is still unavailable after bootstrap. Install App Installer from Microsoft Store and reopen the installer."
    }
    & $winget --version | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "winget is present but cannot run (exit $LASTEXITCODE). Repair App Installer and rerun the installer."
    }
    return $winget
}

function Invoke-WingetInstall {
    param(
        [string]$Id,
        [string]$Name
    )

    $winget = Require-Winget
    Set-Step "安装 $Name" @(
        "请允许系统弹出的安装授权；安装完成后脚本会重新检查工具是否可用",
        "如提示需要重启，请重启电脑后重新运行安装脚本"
    )
    Write-Host "Installing $Name with winget package $Id ..."
    & $winget install --id $Id -e --source winget --accept-source-agreements --accept-package-agreements --disable-interactivity | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "winget install failed for $Id with exit code $LASTEXITCODE"
    }
    Refresh-ProcessPath
}

function Ensure-Git {
    Set-Step "检查 Git" @(
        "Git 用来拉取源码；如果只是运行已下载的源码，可以先不管它"
    )
    $git = Resolve-CommandPath @("git.exe", "git")
    if (-not $git) {
        Invoke-WingetInstall -Id "Git.Git" -Name "Git for Windows"
        $git = Resolve-CommandPath @("git.exe", "git")
    }
    if (-not $git) {
        throw "Git was installed but git.exe is still not visible in PATH. Reopen PowerShell and rerun scripts\install.bat."
    }
    $gitVersion = & $git --version
    if ($LASTEXITCODE -ne 0) { throw "git --version failed with exit code $LASTEXITCODE" }
    Write-Host "Git ready: $gitVersion"
}

function Get-NodeVersion {
    $node = Resolve-CommandPath @("node.exe", "node")
    if (-not $node) {
        return $null
    }

    $raw = & $node -v
    if ($LASTEXITCODE -ne 0 -or "$raw".Trim() -notmatch "^v?(\d+\.\d+\.\d+)") {
        return $null
    }
    return [version]$Matches[1]
}

function Ensure-Node {
    Set-Step "检查 Node.js（Electron 桌面窗口需要）" @(
        "只想用浏览器打开 WebUI 的话，这一步不是必须的"
    )
    $version = Get-NodeVersion
    $npm = Resolve-CommandPath @("npm.cmd", "npm")
    if (-not $version -or $version -lt $NodeMinimumVersion -or -not $npm) {
        Invoke-WingetInstall -Id "OpenJS.NodeJS.LTS" -Name "Node.js LTS"
        $version = Get-NodeVersion
        $npm = Resolve-CommandPath @("npm.cmd", "npm")
    }
    if (-not $version -or $version -lt $NodeMinimumVersion) {
        throw "Node.js >= $NodeMinimumVersion is required. Reopen PowerShell and rerun scripts\install.bat."
    }
    if (-not $npm) {
        throw "npm was not found after Node.js install. Reopen PowerShell and rerun scripts\install.bat."
    }
    $npmVersion = & $npm -v
    if ($LASTEXITCODE -ne 0) { throw "npm --version failed with exit code $LASTEXITCODE. Repair Node.js LTS and retry." }
    Write-Host "Node ready: v$version"
    Write-Host "npm ready: $npmVersion"
}

function Ensure-Uv {
    Set-Step "检查 uv（用来装 Python 环境）" @()
    $uv = Resolve-CommandPath @("uv.exe", "uv")
    if (-not $uv) {
        Invoke-WingetInstall -Id "astral-sh.uv" -Name "uv"
        $uv = Resolve-CommandPath @("uv.exe", "uv")
    }
    if (-not $uv) {
        throw "uv was installed but uv.exe is still not visible in PATH. Reopen PowerShell and rerun scripts\install.bat."
    }
    $uvVersion = & $uv --version
    if ($LASTEXITCODE -ne 0) { throw "uv --version failed with exit code $LASTEXITCODE" }
    Write-Host "uv ready: $uvVersion"
    return $uv
}

function Test-VisualCppRuntime {
    $runtimeRecord = Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" -ErrorAction SilentlyContinue
    if ($null -eq $runtimeRecord -or $runtimeRecord.Installed -ne 1) { return $false }
    $runtimeVersion = $null
    return [version]::TryParse(([string]$runtimeRecord.Version).TrimStart("v"), [ref]$runtimeVersion) -and
        $runtimeVersion -ge $VisualCppMinimumVersion
}

function Ensure-VisualCppRuntime {
    Set-Step "检查 Microsoft Visual C++ x64 运行库" @(
        "Python、Paddle 和 OpenCV 的原生 DLL 需要 VC++ 运行库；缺失时会自动安装",
        "安装需要系统授权；如要求重启，重启后重新运行本脚本"
    )
    if (-not (Test-VisualCppRuntime)) {
        Invoke-WingetInstall -Id "Microsoft.VCRedist.2015+.x64" -Name "Microsoft Visual C++ x64 Runtime"
    }
    if (-not (Test-VisualCppRuntime)) {
        throw "Visual C++ x64 runtime >= $VisualCppMinimumVersion is still missing. Restart Windows if requested and rerun the installer."
    }
}

function Install-Tools {
    # install.bat uses process-only Bypass; never change the user's stored policy.
    Ensure-Git
    Ensure-Node
    Ensure-Uv | Out-Null
    Ensure-VisualCppRuntime
}

function Test-VenvPython {
    if (-not (Test-Path -LiteralPath $VenvPy -PathType Leaf)) {
        return $false
    }

    # A venv can exist with a broken interpreter (moved folder, missing DLLs).
    # Probing it must report "not usable" instead of aborting the installer.
    try {
        $version = & $VenvPy -c "import struct, sys; assert struct.calcsize('P') == 8, '64-bit Python required'; print('.'.join(map(str, sys.version_info[:3])))" 2>$null
    } catch {
        return $false
    }
    return $LASTEXITCODE -eq 0 -and "$version".Trim() -eq $PythonVersion
}

function Ensure-Venv {
    # Check the venv first: a usable one needs no uv at all, so requiring the
    # toolchain before this check would fail an install that had nothing to do.
    if (Test-Path -LiteralPath $VenvDir -PathType Container) {
        if (Test-VenvPython) {
            Write-Host ".venv already uses Python $PythonVersion"
            return
        }
        throw ".venv exists but is not Python $PythonVersion. Remove .venv and rerun scripts\install.bat python."
    }

    $uv = Ensure-Uv

    Write-Host "Ensuring uv-managed Python $PythonVersion is available ..."
    & $uv python install $PythonVersion
    if ($LASTEXITCODE -ne 0) {
        throw "uv python install $PythonVersion failed with exit code $LASTEXITCODE"
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
        if ($configDocument.ocr.use_gpu -isnot [bool]) {
            throw "ocr.use_gpu must be a JSON boolean (true or false), not a string or number: $RuntimeConfig"
        }
        $configuredUseGpu = $configDocument.ocr.use_gpu
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

function Test-PythonRuntimeCompatibility {
    $probe = @"
from importlib.metadata import version
from packaging.version import Version
setuptools_version = Version(version('setuptools'))
assert setuptools_version < Version('$SetuptoolsUpperBound'), f'$SetuptoolsRequirement is required, got {setuptools_version}'
import pkg_resources
import packaging.tags
import distutils.util
import adbutils
import uiautomator2
import cv2
import numpy
import fastapi
import uvicorn
import lxml.etree
import Levenshtein
from python_multipart.multipart import parse_options_header
from PIL import Image
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from paddleocr import PaddleOCR
print(f'python runtime compatibility ready: setuptools={setuptools_version}')
"@
    & $VenvPy -X utf8 -W "ignore:pkg_resources is deprecated as an API:UserWarning" -c $probe
    if ($LASTEXITCODE -ne 0) {
        throw "Python runtime compatibility validation failed with exit code $LASTEXITCODE. Re-run scripts\install.bat python."
    }
}

function Install-PythonDeps {
    Set-Step "选择 Paddle 运行时" @("缺少配置时使用 CPU；已有配置的 ocr.use_gpu 必须是 true 或 false")
    $selectedPaddleVariant = Resolve-PaddleVariant
    $script:ResolvedPaddleVariant = $selectedPaddleVariant
    $variantRequirements = if ($selectedPaddleVariant -eq "gpu") { $GpuRequirements } else { $CpuRequirements }

    foreach ($requirementsPath in @($CommonRequirements, $variantRequirements)) {
        if (-not (Test-Path -LiteralPath $requirementsPath -PathType Leaf)) {
            throw "Missing requirements file: $requirementsPath"
        }
    }

    Ensure-VisualCppRuntime
    Set-Step "准备 Python 虚拟环境（.venv）" @(
        "Python 版本固定为 $PythonVersion；重新安装不会影响 data\ 里的账号和配置"
    )
    Ensure-Venv

    $uv = Ensure-Uv
    Set-Step "安装 Python 依赖（第一次会比较慢，视网速可能十几分钟）" @(
        "装不上通常是网络问题：换成手机热点或稍后重试"
        '国内网络可以先执行：$env:UV_DEFAULT_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple" 再重跑本脚本'
    )
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

    Write-Host "Reapplying legacy adbutils compatibility requirement $SetuptoolsRequirement ..."
    & $uv pip install --python $VenvPy $SetuptoolsRequirement
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install $SetuptoolsRequirement with exit code $LASTEXITCODE"
    }

    Set-Step "校验 Python 依赖与原生运行库" @(
        "此步骤会实际导入 WebUI、OpenCV 和 PaddleOCR，但不会连接模拟器或写入账号配置",
        "GPU 校验失败时检查 NVIDIA 驱动；无 NVIDIA GPU 的电脑请使用 CPU 配置"
    )
    & $uv pip check --python $VenvPy
    if ($LASTEXITCODE -ne 0) { throw "Python dependency consistency check failed with exit code $LASTEXITCODE" }
    Test-PaddleRuntime -SelectedVariant $selectedPaddleVariant
    Test-PythonRuntimeCompatibility
}

function Test-ElectronRuntime {
    $node = Resolve-CommandPath @("node.exe", "node")
    $probe = @'
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const electronPath = require('electron');
const expectedVersion = require('electron/package.json').version;
const result = spawnSync(electronPath, ['-e', 'process.stdout.write(process.versions.electron)'], {
  env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' },
  encoding: 'utf8', timeout: 30000, windowsHide: true,
});
if (result.error) throw result.error;
assert.equal(result.status, 0, result.stderr || 'Electron executable failed to start');
assert.equal(result.stdout.trim(), expectedVersion, 'Electron executable/package version mismatch');
console.log(`Electron runtime ready: ${expectedVersion}`);
'@
    & $node -e $probe
    if ($LASTEXITCODE -ne 0) { throw "Electron executable validation failed with exit code $LASTEXITCODE" }
}

function Install-ElectronDeps {
    if (-not (Test-Path -LiteralPath (Join-Path $ElectronDir "package.json") -PathType Leaf)) {
        throw "Missing Electron package.json: $ElectronDir"
    }

    Ensure-Node
    $npm = Resolve-CommandPath @("npm.cmd", "npm")
    $node = Resolve-CommandPath @("node.exe", "node")

    Set-Step "安装 Electron 依赖（只影响桌面窗口）" @(
        "npm 包与 Electron 可执行文件是两次下载；npm registry 不会改变 Electron 二进制下载地址",
        '二进制下载失败可设置：$env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/" 后重试'
    )
    Write-Host "Installing Electron dependencies in frontend\electron with npm install ..."
    $previousSkipDownload = $env:ELECTRON_SKIP_BINARY_DOWNLOAD
    Push-Location $ElectronDir
    try {
        Remove-Item Env:\ELECTRON_SKIP_BINARY_DOWNLOAD -ErrorAction SilentlyContinue
        & $npm install --include=dev --ignore-scripts=false
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed with exit code $LASTEXITCODE"
        }
        $electronPackage = Join-Path $ElectronDir "node_modules\electron"
        if (-not (Test-Path -LiteralPath (Join-Path $electronPackage "dist\electron.exe") -PathType Leaf) -or
            -not (Test-Path -LiteralPath (Join-Path $electronPackage "path.txt") -PathType Leaf)) {
            $binaryInstaller = Join-Path $electronPackage "install.js"
            if (-not (Test-Path -LiteralPath $binaryInstaller -PathType Leaf)) {
                throw "Electron install.js is missing after npm install: $binaryInstaller"
            }
            & $node $binaryInstaller
            if ($LASTEXITCODE -ne 0) { throw "Electron binary download failed with exit code $LASTEXITCODE" }
        }
        Test-ElectronRuntime
    } finally {
        if ($null -eq $previousSkipDownload) {
            Remove-Item Env:\ELECTRON_SKIP_BINARY_DOWNLOAD -ErrorAction SilentlyContinue
        } else {
            $env:ELECTRON_SKIP_BINARY_DOWNLOAD = $previousSkipDownload
        }
        Pop-Location
    }
}

function Install-QQBot {
    Ensure-Venv
    $setupScript = Join-Path $Root "backend\core\qq_bot.py"
    & $VenvPy -X utf8 $setupScript install
    if ($LASTEXITCODE -ne 0) {
        throw "NapCat installation failed with exit code $LASTEXITCODE"
    }
}

try {
    Write-Head "AutoScriptor 安装（目标：$Target）"
    Write-Host "    源码目录：$Root"
    Write-Host "    日志文件：$InstallLogPath"
    Test-InstallPrerequisites

    if ($Target -eq "tools" -or $Target -eq "all") {
        Install-Tools
    }

    if ($Target -eq "python" -or $Target -eq "all") {
        Install-PythonDeps
    }

    if ($Target -eq "electron" -or $Target -eq "all") {
        Install-ElectronDeps
    }

    if ($Target -eq "all" -and -not $WithQQ) {
        if (Test-Path -LiteralPath (Join-Path $Root ".autoscriptor\qq-bot\autoscriptor.json")) {
            $WithQQ = $true
        } elseif (-not $NonInteractive) {
            Write-Host ""
            Write-Host "可选：QQ 通知机器人（第三方 NapCat，约 112 MB）。" -ForegroundColor DarkGray
            Write-Host "      需要手机扫码登录一个 QQ 小号；不装也完全不影响任务执行。" -ForegroundColor DarkGray
            $answer = Read-Host "    现在安装吗？[y/N]"
            $WithQQ = $answer -match '^(y|yes)$'
        }
    }
    if ($Target -eq "qq" -or $WithQQ) {
        Install-QQBot
    }
} catch {
    Fail-Install `
        -Step $script:CurrentStep `
        -Reason $_.Exception.Message `
        -Actions $script:CurrentHints
}

$paddleSummary = if ($null -ne $script:ResolvedPaddleVariant) { $script:ResolvedPaddleVariant } else { "未安装" }
Write-Host ""
Write-Host "================ 安装完成 ================" -ForegroundColor Green
Write-Host "  Paddle 运行时：$paddleSummary"
Write-Host "  本次目标：$Target（tools / python / electron / qq 仅安装各自部分）"
Write-Host "  MuMu 和游戏需另行安装；OCR 模型在首次使用时联网下载。"
Write-Host ""
Write-Host "  下一步：" -ForegroundColor Cyan
Write-Host "    1) 启动（二选一）"
Write-Host "         浏览器版：双击 webui.bat   （会打印形如 http://127.0.0.1:5000 的地址）"
Write-Host "         桌面窗口：双击 start.bat"
Write-Host "    2) 在打开的页面里新建账号 → 选角色 → 打开要跑的任务"
Write-Host "    3) 设置里的「启动诊断」可以检查 MuMu 和 OCR 是否正常"
Write-Host ""
Write-Host "  完整教程：docs\AutoScriptor\GETTING-STARTED.md"
Write-Host "  本次安装日志：$InstallLogPath"
Write-Host "==========================================" -ForegroundColor Green
exit 0
