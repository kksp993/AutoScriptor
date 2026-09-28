# Offline checks: do not install a robot, touch firewall rules, log in, or send messages.
$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path $PSScriptRoot -Parent
$scriptPath = Join-Path $repositoryRoot "scripts\qq-robot-standalone\robot.ps1"
$parseTokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$parseTokens, [ref]$parseErrors) | Out-Null
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
. $scriptPath

$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("qq robot checks " + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$RuntimeRoot = Join-Path $testRoot "runtime"
$checks = 0

function Assert-Check {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
    $script:checks++
}

function Assert-Rejected {
    param([scriptblock]$Operation)
    $rejected = $false
    try { & $Operation } catch { $rejected = $true }
    Assert-Check $rejected "Expected the unsafe operation to be rejected."
}

try {
    foreach ($address in @("10.0.0.1", "172.16.1.2", "172.31.255.254", "192.168.1.20", "100.64.0.1", "100.127.1.2")) {
        Assert-PrivateIPv4 $address
        $checks++
    }
    foreach ($address in @("0.0.0.0", "127.0.0.1", "8.8.8.8", "172.32.1.1", "100.128.1.1", "192.168.1.0/24", "*", "localhost", "::1", "10.1", "010.1.1.1", "192.168.1.999")) {
        Assert-Rejected { Assert-PrivateIPv4 $address }
    }
    Assert-Rejected { New-RobotConfiguration $RuntimeRoot "10.1.1.1" "10.1.1.1" }
    Assert-Check (-not (Test-Path $RuntimeRoot)) "Rejected settings must not write runtime files."

    $settings = New-RobotConfiguration $RuntimeRoot "192.168.1.20" "192.168.1.10"
    $onebot = Get-Content -Raw -Encoding UTF8 (Join-Path $RuntimeRoot "napcat\config\onebot11.json") | ConvertFrom-Json
    $management = Get-Content -Raw -Encoding UTF8 (Join-Path $RuntimeRoot "napcat\config\webui.json") | ConvertFrom-Json
    $server = $onebot.network.httpServers[0]
    Assert-Check ($onebot.network.httpServers.Count -eq 1) "Only one HTTP server is needed."
    Assert-Check ($server.host -eq "192.168.1.20" -and $server.port -eq 3000) "Bind only the requested adapter."
    Assert-Check ($server.token -ceq $settings.access_token -and $server.token -cmatch '^[0-9a-f]{64}$') "Invalid HTTP token."
    Assert-Check (-not $server.enableCors -and -not $server.enableWebsocket) "Do not open extra transports."
    Assert-Check ($management.host -eq "127.0.0.1" -and $management.port -eq 6099) "Management must stay local."
    Assert-Check ($management.token -cne $server.token) "Use distinct random tokens."
    Assert-Rejected { Read-Settings }
    foreach ($filename in $RequiredFiles) {
        $path = Join-Path $RuntimeRoot $filename
        New-Item -ItemType Directory -Path (Split-Path $path -Parent) -Force | Out-Null
        [System.IO.File]::WriteAllText($path, "test stub")
    }
    $loaded = Read-Settings
    Assert-Check ($loaded.access_token -ceq $settings.access_token) "Reading must preserve the generated token."

    # Shadow firewall commands; no system policy is queried or modified by this test.
    $script:createdRule = $null
    $script:removedRule = $null
    $script:existingRules = @()
    $script:firewallEnabled = $true
    function Get-NetFirewallProfile { param($PolicyStore); [pscustomobject]@{ Enabled = $script:firewallEnabled; DefaultInboundAction = "Block" } }
    function Get-NetFirewallRule { param($PolicyStore); $script:existingRules }
    function New-NetFirewallRule {
        param($Name, $Direction, $Action, $Enabled, $Profile, $Protocol, $LocalPort, $LocalAddress, $RemoteAddress, $Program, $EdgeTraversalPolicy, $DisplayName)
        $script:createdRule = @{} + $PSBoundParameters
    }
    function Remove-NetFirewallRule {
        param($Name, $Confirm)
        $script:removedRule = $Name
    }
    function Get-NetFirewallAddressFilter {
        [CmdletBinding()] param([Parameter(ValueFromPipeline = $true)]$Rule)
        process { [pscustomobject]@{ RemoteAddress = @($settings.client_address); LocalAddress = @($settings.bot_address) } }
    }
    function Get-NetFirewallPortFilter {
        [CmdletBinding()] param([Parameter(ValueFromPipeline = $true)]$Rule)
        process { [pscustomobject]@{ LocalPort = @("3000"); Protocol = "TCP" } }
    }
    function Get-NetFirewallApplicationFilter {
        [CmdletBinding()] param([Parameter(ValueFromPipeline = $true)]$Rule)
        process { [pscustomobject]@{ Program = (Join-Path $RuntimeRoot "node.exe") } }
    }
    # Fail before testing if any firewall command resolves to a real system command.
    foreach ($commandName in @("Get-NetFirewallProfile", "Get-NetFirewallRule", "New-NetFirewallRule", "Remove-NetFirewallRule", "Get-NetFirewallAddressFilter", "Get-NetFirewallPortFilter", "Get-NetFirewallApplicationFilter")) {
        Assert-Check ((Get-Command $commandName).ScriptBlock.File -eq $PSCommandPath) "Missing local firewall stub: $commandName"
    }
    Set-RobotFirewall $settings
    Assert-Check ($createdRule.RemoteAddress -eq "192.168.1.10") "Firewall must restrict the source IP."
    Assert-Check ($createdRule.LocalAddress -eq "192.168.1.20" -and $createdRule.LocalPort -eq 3000) "Firewall must not expose management."
    Assert-Check ($createdRule.Program -eq (Join-Path $RuntimeRoot "node.exe")) "Firewall must restrict the executable."
    Assert-Check ($createdRule.EdgeTraversalPolicy -eq "Block") "Do not enable edge traversal."
    $script:existingRules = @([pscustomobject]@{ Name = $settings.firewall_rule })
    Set-RobotFirewall $settings
    Assert-Check ($removedRule -eq $settings.firewall_rule) "Reinstall should replace its own rule only."
    Assert-Rejected { Assert-RobotFirewall $settings }
    $script:existingRules = @([pscustomobject]@{ Name = $settings.firewall_rule; Enabled = "True"; Direction = "Inbound"; Action = "Allow" })
    Assert-RobotFirewall $settings
    $checks++
    function Get-NetFirewallAddressFilter {
        [CmdletBinding()] param([Parameter(ValueFromPipeline = $true)]$Rule)
        process { [pscustomobject]@{ RemoteAddress = @("Any"); LocalAddress = @($settings.bot_address) } }
    }
    Assert-Rejected { Assert-RobotFirewall $settings }
    $script:firewallEnabled = $false
    Assert-Rejected { Set-RobotFirewall $settings }

    $archive = Join-Path $testRoot "bad.zip"
    [System.IO.File]::WriteAllText($archive, "not a release")
    $destination = Join-Path $testRoot "extracted"
    Assert-Rejected { Expand-VerifiedArchive $archive $destination }
    Assert-Check (-not (Test-Path $destination)) "Checksum must be verified before extraction."

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    foreach ($name in @("../escape.txt", "C:/escape.txt", "/escape.txt", "..\escape.txt")) {
        Remove-Item -LiteralPath $archive
        $package = [System.IO.Compression.ZipFile]::Open($archive, "Create")
        try { $package.CreateEntry($name) | Out-Null } finally { $package.Dispose() }
        $ArchiveHash = (Get-FileHash $archive -Algorithm SHA256).Hash
        Assert-Rejected { Expand-VerifiedArchive $archive $destination }
        Assert-Check (-not (Test-Path $destination)) "Unsafe paths must be rejected before extraction."
    }

    Write-Host "PASS: $checks standalone robot checks (offline, no firewall changes)."
} finally {
    Remove-Item -LiteralPath $testRoot -Recurse -Force
}
