param(
    [ValidateSet("install", "start", "connection")]
    [string]$Action = "install",
    [string]$BotAddress = "",
    [string]$ClientAddress = ""
)

# Standalone Windows PowerShell 5.1 entry. No AutoScriptor/Python/npm dependency.
$ErrorActionPreference = "Stop"
$RuntimeRoot = Join-Path $PSScriptRoot "runtime"
$ReleaseVersion = "v4.18.9"
$ArchiveHash = "234f2b9341d355d107881ce486d6699f529300d644282e25af452717d00a50da"
$ArchiveUrl = "https://github.com/NapNeko/NapCatQQ/releases/download/$ReleaseVersion/NapCat.Shell.Windows.Node.zip"
$RequiredFiles = @("node.exe", "index.js", "wrapper.node", "QQNT.dll", "napcat\napcat.mjs")
$Utf8 = [System.Text.UTF8Encoding]::new($false)

function Assert-PrivateIPv4 {
    param([string]$Address)
    if ($Address -notmatch '^\d{1,3}(\.\d{1,3}){3}$') {
        throw "Use a single LAN/VPN IPv4 address, not a hostname, subnet or wildcard: $Address"
    }
    $parsed = [System.Net.IPAddress]::Parse($Address)
    $octets = $parsed.GetAddressBytes()
    $isPrivate = $octets[0] -eq 10 -or
        ($octets[0] -eq 172 -and $octets[1] -ge 16 -and $octets[1] -le 31) -or
        ($octets[0] -eq 192 -and $octets[1] -eq 168) -or
        ($octets[0] -eq 100 -and $octets[1] -ge 64 -and $octets[1] -le 127)
    if (-not $isPrivate -or $parsed.ToString() -ne $Address) {
        throw "Only canonical private LAN/VPN IPv4 addresses are supported: $Address"
    }
}

function Assert-LocalAddress {
    param([string]$Address, [int]$Port)
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse($Address), $Port)
    try {
        $listener.Server.ExclusiveAddressUse = $true
        $listener.Start()
    } catch {
        throw "Cannot bind ${Address}:$Port. Check the local IP and whether the port is occupied."
    } finally {
        $listener.Stop()
    }
}

function New-RandomToken {
    $buffer = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($buffer) } finally { $generator.Dispose() }
    return [BitConverter]::ToString($buffer).Replace("-", "").ToLowerInvariant()
}

function Write-JsonFile {
    param([string]$Path, [object]$Document)
    [System.IO.File]::WriteAllText($Path, ($Document | ConvertTo-Json -Depth 20), $Utf8)
}

function Read-Settings {
    foreach ($relativePath in $RequiredFiles + @("remote-setup.json")) {
        if (-not (Test-Path -LiteralPath (Join-Path $RuntimeRoot $relativePath) -PathType Leaf)) {
            throw "Missing runtime file: $relativePath. Do not overwrite a partial/existing installation."
        }
    }
    $settings = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $RuntimeRoot "remote-setup.json") | ConvertFrom-Json
    Assert-PrivateIPv4 $settings.bot_address
    Assert-PrivateIPv4 $settings.client_address
    if ($settings.bot_address -eq $settings.client_address -or
        $settings.access_token -cnotmatch '^[0-9a-f]{64}$' -or
        $settings.web_token -cnotmatch '^[0-9a-f]{64}$' -or
        $settings.firewall_rule -cnotmatch '^QQRobot-[0-9a-f]{32}$') {
        throw "Invalid standalone robot settings; no firewall or runtime changes made."
    }
    return $settings
}

function New-RobotConfiguration {
    param([string]$Directory, [string]$ServerAddress, [string]$AllowedAddress)
    Assert-PrivateIPv4 $ServerAddress
    Assert-PrivateIPv4 $AllowedAddress
    if ($ServerAddress -eq $AllowedAddress) { throw "The two computers must have different IP addresses." }
    $settings = [ordered]@{
        version = $ReleaseVersion
        bot_address = $ServerAddress
        client_address = $AllowedAddress
        access_token = New-RandomToken
        web_token = New-RandomToken
        firewall_rule = "QQRobot-$([Guid]::NewGuid().ToString('N'))"
    }
    $configDirectory = Join-Path $Directory "napcat\config"
    New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
    Write-JsonFile (Join-Path $configDirectory "onebot11.json") @{
        network = @{
            httpServers = @(@{
                name = "ScriptComputer"; enable = $true
                host = $ServerAddress; port = 3000; token = $settings.access_token
                enableCors = $false; enableWebsocket = $false
                messagePostFormat = "array"; debug = $false
            })
            httpSseServers = @(); httpClients = @(); websocketServers = @()
            websocketClients = @(); plugins = @()
        }
    }
    Write-JsonFile (Join-Path $configDirectory "webui.json") @{
        host = "127.0.0.1"; port = 6099; token = $settings.web_token
        autoLoginAccount = ""; disableWebUI = $false; enableXForwardedFor = $false
    }
    Write-JsonFile (Join-Path $Directory "remote-setup.json") $settings
    return [pscustomobject]$settings
}

function Expand-VerifiedArchive {
    param([string]$Archive, [string]$Destination)
    if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash -ne $ArchiveHash) {
        throw "SHA256 mismatch. Refusing to extract or execute this download."
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $package = [System.IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        $totalSize = 0L
        foreach ($entry in $package.Entries) {
            $name = $entry.FullName.Replace('\', '/')
            if ($name.StartsWith('/') -or $name.Contains(':') -or $name.Split('/') -contains '..' -or
                (($entry.ExternalAttributes -shr 16) -band 61440) -eq 40960) {
                throw "Unsafe archive entry; refusing extraction."
            }
            $totalSize += $entry.Length
            if ($totalSize -gt 2GB) { throw "Unexpectedly large archive." }
        }
    } finally { $package.Dispose() }
    [System.IO.Compression.ZipFile]::ExtractToDirectory($Archive, $Destination)
}

function Test-NativeRuntime {
    param([string]$Directory)
    $processInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $processInfo.FileName = Join-Path $Directory "node.exe"
    $processInfo.WorkingDirectory = $Directory
    $processInfo.Arguments = '-e "process.dlopen({exports:{}}, require(''path'').resolve(''wrapper.node'')); process.exit(0)"'
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true
    $processInfo.RedirectStandardError = $true
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $processInfo
    try {
        $process.Start() | Out-Null
        $errorOutput = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(30000)) {
            $process.Kill()
            $process.WaitForExit()
            throw "Native runtime probe timed out. Installation not accepted."
        }
        if ($process.ExitCode -ne 0) {
            throw "Native runtime probe failed. Check Windows VC++ x64 runtime dependencies: $($errorOutput.Result)"
        }
    } finally { $process.Dispose() }
}

function Assert-FirewallEnabled {
    # Keep Windows default-deny behavior; never disable the firewall or open the management port.
    $profiles = @(Get-NetFirewallProfile -PolicyStore ActiveStore)
    if ($profiles.Count -eq 0 -or @($profiles | Where-Object {
        -not $_.Enabled -or $_.DefaultInboundAction -ne "Block"
    }).Count -gt 0) {
        throw "Windows Firewall must be enabled with default inbound Block on every profile."
    }
}

function Assert-RobotFirewall {
    param([object]$Settings)
    Assert-FirewallEnabled
    $rules = @(Get-NetFirewallRule -PolicyStore ActiveStore | Where-Object { $_.Name -eq $Settings.firewall_rule })
    if ($rules.Count -ne 1 -or $rules[0].Enabled -ne "True" -or
        $rules[0].Direction -ne "Inbound" -or $rules[0].Action -ne "Allow") {
        throw "Robot firewall rule is missing or inactive. Rerun 1-install.cmd as administrator."
    }
    $addressFilter = $rules[0] | Get-NetFirewallAddressFilter
    $portFilter = $rules[0] | Get-NetFirewallPortFilter
    $applicationFilter = $rules[0] | Get-NetFirewallApplicationFilter
    if (@($addressFilter.RemoteAddress).Count -ne 1 -or @($addressFilter.RemoteAddress)[0] -ne $Settings.client_address -or
        @($addressFilter.LocalAddress).Count -ne 1 -or @($addressFilter.LocalAddress)[0] -ne $Settings.bot_address -or
        @($portFilter.LocalPort).Count -ne 1 -or @($portFilter.LocalPort)[0] -ne "3000" -or
        $portFilter.Protocol -notin @("TCP", "6") -or
        $applicationFilter.Program -ne (Join-Path $RuntimeRoot "node.exe")) {
        throw "Robot firewall scope differs from this setup. Rerun 1-install.cmd as administrator."
    }
}

function Set-RobotFirewall {
    param([object]$Settings)
    Assert-FirewallEnabled
    $ruleArguments = @{
        Name = $Settings.firewall_rule
        Direction = "Inbound"; Action = "Allow"; Enabled = "True"; Profile = "Any"
        Protocol = "TCP"; LocalPort = 3000
        LocalAddress = $Settings.bot_address; RemoteAddress = $Settings.client_address
        Program = (Join-Path $RuntimeRoot "node.exe")
        EdgeTraversalPolicy = "Block"
    }
    $existing = @(Get-NetFirewallRule -PolicyStore PersistentStore | Where-Object { $_.Name -eq $Settings.firewall_rule })
    if ($existing.Count -gt 0) {
        # Replace only this installation's uniquely named rule, never other rules.
        Remove-NetFirewallRule -Name $Settings.firewall_rule -Confirm:$false
    }
    New-NetFirewallRule @ruleArguments -DisplayName "QQ Robot - script computer only" | Out-Null
}

function Show-Connection {
    param([object]$Settings)
    $instructions = @"
Use these values on the SCRIPT computer, in AutoScriptor > QQ notifications:
HTTP address: http://$($Settings.bot_address):3000
Access token: $($Settings.access_token)
Allowed script computer: $($Settings.client_address)
Choose your recipient QQ/group number yourself. Test before enabling notifications.
Do NOT click 'Use local configuration' for this remote deployment.

Robot management (open only on the ROBOT computer):
http://127.0.0.1:6099/webui?token=$($Settings.web_token)

Firewall rule name (for removal): $($Settings.firewall_rule)
This file contains credentials. Do not publish it or send it in a group chat.
"@
    [System.IO.File]::WriteAllText((Join-Path $RuntimeRoot "connection.txt"), $instructions, $Utf8)
    Write-Host $instructions
}

function Install-Robot {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Right-click 1-install.cmd and choose Run as administrator (needed for the scoped firewall rule)."
    }
    if (-not [Environment]::Is64BitProcess -or $env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
        throw "Windows 10/11 x64 and 64-bit Windows PowerShell are required."
    }
    Assert-FirewallEnabled
    if (Test-Path -LiteralPath $RuntimeRoot) {
        $settings = Read-Settings
        if (($BotAddress -and $BotAddress -ne $settings.bot_address) -or
            ($ClientAddress -and $ClientAddress -ne $settings.client_address)) {
            throw "Existing IP settings differ. See README before changing network configuration."
        }
        Write-Host "Existing installation kept; repairing only its scoped firewall rule."
    } else {
        if (-not $BotAddress) { $BotAddress = Read-Host "ROBOT computer LAN/VPN IPv4 (this computer)" }
        if (-not $ClientAddress) { $ClientAddress = Read-Host "SCRIPT computer LAN/VPN IPv4 (the other computer)" }
        Assert-PrivateIPv4 $BotAddress
        Assert-PrivateIPv4 $ClientAddress
        if ($BotAddress -eq $ClientAddress) { throw "The two computer IP addresses must differ." }
        Assert-LocalAddress $BotAddress 3000
        Assert-LocalAddress "127.0.0.1" 6099
        $staging = Join-Path $PSScriptRoot (".install-" + [Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $staging | Out-Null
        try {
            $archive = Join-Path $staging "NapCat.zip"
            Write-Host "Downloading official NapCat $ReleaseVersion (~110 MiB). Manual QQ login required."
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $previousProgress = $ProgressPreference
            try {
                $ProgressPreference = "SilentlyContinue"
                Invoke-WebRequest -UseBasicParsing -Uri $ArchiveUrl -OutFile $archive -TimeoutSec 300
            } finally { $ProgressPreference = $previousProgress }
            $extracted = Join-Path $staging "unpacked"
            Expand-VerifiedArchive $archive $extracted
            $candidates = @($extracted) + @(Get-ChildItem -LiteralPath $extracted -Directory | ForEach-Object { $_.FullName })
            $runtimeCandidate = $null
            foreach ($candidate in $candidates) {
                $missing = @($RequiredFiles | Where-Object { -not (Test-Path -LiteralPath (Join-Path $candidate $_) -PathType Leaf) })
                if ($missing.Count -eq 0) { $runtimeCandidate = $candidate; break }
            }
            if (-not $runtimeCandidate) { throw "Official archive layout changed. Installation refused." }
            Test-NativeRuntime $runtimeCandidate
            $settings = New-RobotConfiguration $runtimeCandidate $BotAddress $ClientAddress
            for ($attempt = 0; $attempt -lt 5; $attempt++) {
                try {
                    [System.IO.Directory]::Move($runtimeCandidate, $RuntimeRoot)
                    break
                } catch [System.IO.IOException], [System.UnauthorizedAccessException] {
                    if ($attempt -eq 4 -or (Test-Path -LiteralPath $RuntimeRoot) -or
                        ($_.Exception.HResult -band 65535) -notin @(5, 32)) { throw }
                    Start-Sleep -Milliseconds (250 * [Math]::Pow(2, $attempt))
                }
            }
        } finally {
            # Only this invocation's unique staging directory is ever removed.
            if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
        }
    }
    Set-RobotFirewall $settings
    Assert-RobotFirewall $settings
    Show-Connection $settings
    Write-Host "Setup complete. Close this administrator window. Run 2-start.cmd normally, then log in to QQ."
}

function Start-Robot {
    $settings = Read-Settings
    Assert-RobotFirewall $settings
    Assert-LocalAddress $settings.bot_address 3000
    Assert-LocalAddress "127.0.0.1" 6099
    Show-Connection $settings
    Write-Host "Keep this window open. Do not allow additional broad firewall access if Windows prompts."
    $previousMode = $env:NAPCAT_DISABLE_MULTI_PROCESS
    Push-Location $RuntimeRoot
    try {
        $env:NAPCAT_DISABLE_MULTI_PROCESS = "1"
        & (Join-Path $RuntimeRoot "node.exe") "index.js"
        if ($LASTEXITCODE -ne 0) { throw "Robot exited with code $LASTEXITCODE. See the output above." }
    } finally {
        $env:NAPCAT_DISABLE_MULTI_PROCESS = $previousMode
        Pop-Location
    }
}

# Dot-sourcing exposes functions for offline tests without downloads or host changes.
if ($MyInvocation.InvocationName -eq ".") { return }
$operationLock = $null
try {
    $operationLock = [System.IO.File]::Open((Join-Path $PSScriptRoot ".operation.lock"), "OpenOrCreate", "ReadWrite", "None")
    switch ($Action) {
        "install" { Install-Robot }
        "start" { Start-Robot }
        "connection" { Show-Connection (Read-Settings) }
    }
} catch {
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "If the operation lock is occupied, use the existing robot window; do not start a second copy."
    exit 1
} finally {
    if ($operationLock) { $operationLock.Dispose() }
}
