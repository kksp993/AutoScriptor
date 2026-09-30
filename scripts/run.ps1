param(
    [ValidateSet("webui", "electron", "qq")]
    [string]$Target = "webui",

    [int]$Port = 0,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AppArgs
)

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
$Root = (Resolve-Path -Path (Join-Path $ScriptDir "..")).Path
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$GuiScript = Join-Path $Root "backend\webui\gui.py"
$ElectronDir = Join-Path $Root "frontend\electron"
$InstallHint = ".\scripts\install.bat"

function Write-Head {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Fail-Run {
    param(
        [string]$Step,
        [string]$Reason,
        [string[]]$Actions
    )
    Write-Host ""
    Write-Host "================ 启动没有完成 ================" -ForegroundColor Red
    Write-Host "  步骤：$Step"
    Write-Host "  原因：$Reason"
    if ($Actions -and $Actions.Count -gt 0) {
        Write-Host "  你可以这样做："
        $index = 1
        foreach ($action in $Actions) {
            Write-Host "    $index) $action"
            $index++
        }
    }
    Write-Host "=============================================" -ForegroundColor Red
    exit 1
}

function Require-File {
    param(
        [string]$Path,
        [string]$Step,
        [string]$Reason,
        [string[]]$Actions
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Fail-Run -Step $Step -Reason $Reason -Actions $Actions
    }
}

function Find-Npm {
    foreach ($name in @("npm.cmd", "npm")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $cmd) { return $cmd.Source }
    }
    return $null
}

function Test-PortFree {
    param([int]$Candidate)
    $listener = $null
    try {
        # ExclusiveAddressUse 必须显式打开：.NET 在 Windows 上默认可能带上
        # SO_REUSEADDR，那样探测会把「别人正在监听」的端口也报成空闲。
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Candidate)
        $listener.ExclusiveAddressUse = $true
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($listener) { $listener.Stop() }
    }
}

function Test-AutoScriptorOnPort {
    # 端口被占时先问一句「是不是自己已经在跑」：新手最常见的困惑就是
    # 「我双击了但没反应」——其实是上一次的实例还在后台。
    param([int]$Candidate)
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Candidate/api/init-status" `
            -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        return $response.StatusCode -eq 200 -and $response.Content -match 'ready'
    } catch {
        return $false
    }
}

function Resolve-WebUiPort {
    # 端口优先取 -Port，其次环境变量，最后 5000；被占用就往后顺延。
    # 这里先挑好并写回环境变量，后端照它监听，所以打印出来的地址确实能打开。
    param([int]$Requested)

    $preferred = 5000
    if ($Requested -gt 0) {
        $preferred = $Requested
    } elseif ($env:AUTOSCRIPTOR_PORT) {
        $parsed = 0
        if ([int]::TryParse($env:AUTOSCRIPTOR_PORT, [ref]$parsed) -and $parsed -ge 1 -and $parsed -le 65535) {
            $preferred = $parsed
        } else {
            Fail-Run -Step "读取端口设置" -Reason "环境变量 AUTOSCRIPTOR_PORT 不是 1-65535 的整数：$($env:AUTOSCRIPTOR_PORT)" -Actions @(
                "删掉它：Remove-Item Env:\AUTOSCRIPTOR_PORT",
                '或改成合法端口：$env:AUTOSCRIPTOR_PORT = ''8080'''
            )
        }
    }

    if ($preferred -lt 1 -or $preferred -gt 65535) {
        Fail-Run -Step "校验端口参数" -Reason "-Port 必须在 1-65535 之间，收到 $preferred" -Actions @(
            "换一个端口，例如：.\scripts\run.bat webui -Port 8080"
        )
    }

    if (Test-PortFree -Candidate $preferred) { return $preferred }

    if (Test-AutoScriptorOnPort -Candidate $preferred) {
        Write-Host ""
        Write-Host "    AutoScriptor 已经在运行了。" -ForegroundColor Yellow
        Write-Host "    地址：http://127.0.0.1:$preferred" -ForegroundColor Green
        Write-Host "    已经在运行的实例只能有一个；要重启就先在它的窗口按 Ctrl+C 停掉。" -ForegroundColor DarkGray
        try {
            Start-Process "http://127.0.0.1:$preferred" | Out-Null
            Write-Host "    已尝试帮你打开浏览器。" -ForegroundColor DarkGray
        } catch {
            Write-Host "    浏览器没有自动打开，请手动复制上面的地址。" -ForegroundColor DarkGray
        }
        exit 0
    }

    for ($candidate = $preferred + 1; $candidate -le [Math]::Min($preferred + 20, 65535); $candidate++) {
        if (Test-PortFree -Candidate $candidate) {
            Write-Host "    端口 $preferred 已被其它程序占用，本次改用 $candidate。" -ForegroundColor Yellow
            Write-Host "    想固定端口：启动时加 -Port $candidate" -ForegroundColor DarkGray
            return $candidate
        }
    }

    Fail-Run -Step "选择监听端口" -Reason "从 $preferred 起连续 20 个端口都被占用" -Actions @(
        "关掉占用端口的程序后重试",
        "或指定别的端口：.\scripts\run.bat webui -Port 9000",
        "查看谁占着：Get-NetTCPConnection -LocalPort $preferred -ErrorAction SilentlyContinue"
    )
}

if ($Target -eq "qq") {
    Require-File -Path $VenvPy -Step "检查运行环境" -Reason "找不到 Python 虚拟环境：$VenvPy" -Actions @(
        "先跑一次安装：$InstallHint",
        "装完再运行：.\scripts\run.bat qq"
    )
    $setupScript = Join-Path $Root "backend\core\qq_bot.py"
    Require-File -Path $setupScript -Step "检查 QQ 机器人入口" -Reason "找不到 $setupScript" -Actions @(
        "确认仓库完整（git status 应显示无删除），或重新拉取源码"
    )
    & $VenvPy -X utf8 $setupScript start @AppArgs
    exit $LASTEXITCODE
}

if ($Target -eq "webui") {
    Require-File -Path $VenvPy -Step "检查运行环境" -Reason "找不到 Python 虚拟环境：$VenvPy" -Actions @(
        "先跑一次安装（会自动装好 Python 依赖）：$InstallHint",
        "装完再启动：.\webui.bat"
    )
    Require-File -Path $GuiScript -Step "检查后端入口" -Reason "找不到 $GuiScript" -Actions @(
        "确认仓库完整（git status 应显示无删除），或重新拉取源码"
    )

    Write-Head "启动 WebUI"
    $webuiPort = Resolve-WebUiPort -Requested $Port
    $env:AUTOSCRIPTOR_PORT = [string]$webuiPort
    Write-Host "    地址：http://127.0.0.1:$webuiPort" -ForegroundColor Green
    Write-Host "    停止：在这个窗口按 Ctrl+C" -ForegroundColor DarkGray
    if (-not (Test-Path -LiteralPath (Join-Path $Root "data\config.json") -PathType Leaf)) {
        # 没有 config.json 也能跑：后端会读 config.template.json 的默认值。
        Write-Host "    提示：还没有 data\config.json，将使用模板里的默认配置。" -ForegroundColor DarkGray
    }
    Write-Host ""

    & $VenvPy -X utf8 $GuiScript @AppArgs
    exit $LASTEXITCODE
}

# ── Electron ──
$npm = Find-Npm
if (-not $npm) {
    Fail-Run -Step "检查 Node.js" -Reason "找不到 npm，Electron 桌面窗口需要它" -Actions @(
        "运行安装脚本（会自动装 Node.js 与 Electron 依赖）：$InstallHint electron",
        "只想用浏览器版的话，改成运行：.\webui.bat"
    )
}

Require-File -Path (Join-Path $ElectronDir "node_modules\electron\package.json") `
    -Step "检查 Electron 依赖" `
    -Reason "frontend\electron\node_modules 里没有 electron" `
    -Actions @(
        "运行：$InstallHint electron",
        "只想用浏览器版的话，改成运行：.\webui.bat"
    )

if ($Port -gt 0) {
    if ($Port -lt 1 -or $Port -gt 65535) {
        Fail-Run -Step "校验端口参数" -Reason "-Port 必须在 1-65535 之间，收到 $Port" -Actions @(
            "换一个端口，例如：.\start.bat -Port 8080"
        )
    }
    # Electron 主进程读同一个变量挑端口，两边必须一致。
    $env:AUTOSCRIPTOR_PORT = [string]$Port
}

Write-Head "启动 Electron 桌面窗口"
Write-Host "    停止：关掉窗口，或在托盘图标上退出" -ForegroundColor DarkGray
Write-Host ""

Push-Location $ElectronDir
try {
    & $npm start
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
