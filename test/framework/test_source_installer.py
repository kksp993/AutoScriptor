"""Exercise installer functions in isolated PowerShell, never installing host tools."""

import base64
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("powershell.exe")


@unittest.skipUnless(os.name == "nt" and POWERSHELL, "Requires Windows PowerShell 5.1")
class SourceInstallerTests(unittest.TestCase):
    def run_probe(self, body: str) -> None:
        with tempfile.TemporaryDirectory(prefix="installer checks \u5b89\u88c5 ") as temporary_root:
            installer_path = str(PROJECT_ROOT / "scripts" / "install.ps1").replace("'", "''")
            fixture_path = temporary_root.replace("'", "''")
            command = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$parseErrors = $null
$syntax = [System.Management.Automation.Language.Parser]::ParseFile(
    '{installer_path}', [ref]$null, [ref]$parseErrors)
if ($parseErrors.Count) {{ throw ($parseErrors | Out-String) }}
# Load definitions only: never run the installer's top-level entry point.
foreach ($statement in $syntax.EndBlock.Statements) {{
    if ($statement -is [System.Management.Automation.Language.FunctionDefinitionAst]) {{
        Invoke-Expression $statement.Extent.Text
    }}
}}
$Root = '{fixture_path}'
$ElectronDir = Join-Path $Root 'electron'
$RuntimeConfig = Join-Path $Root 'config.json'
$PaddleVariant = 'auto'
$VisualCppMinimumVersion = [version]'14.40.0.0'
function Assert-Check([bool]$Condition, [string]$Message) {{
    if (-not $Condition) {{ throw $Message }}
}}
function Assert-Rejected([scriptblock]$Operation, [string]$Message) {{
    $rejected = $false
    try {{ & $Operation }} catch {{ $rejected = $true }}
    Assert-Check $rejected $Message
}}
{body}
"""
            encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
            result = subprocess.run(
                [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-OutputFormat", "Text", "-EncodedCommand", encoded],
                cwd=temporary_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_path_refresh_includes_app_execution_aliases(self):
        self.run_probe(r"""
$env:LOCALAPPDATA = Join-Path $Root 'local app data'
Refresh-ProcessPath
$windowsApps = Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps'
Assert-Check (($env:Path -split ';') -contains $windowsApps) 'Missing winget alias directory'
""")

    def test_preflight_rejects_incomplete_sources_and_accepts_unicode_path(self):
        self.run_probe(r"""
Assert-Rejected { Test-InstallPrerequisites } 'An incomplete source archive must stop before installing tools'
foreach ($relativePath in @('requirements.txt', 'requirements-cpu.txt', 'requirements-gpu.txt', 'data\config.template.json', 'backend\webui\gui.py', 'frontend\electron\package.json')) {
    $fixtureFile = Join-Path $Root $relativePath
    New-Item -ItemType Directory -Path (Split-Path $fixtureFile -Parent) -Force | Out-Null
    [IO.File]::WriteAllText($fixtureFile, '')
}
Test-InstallPrerequisites
Assert-Check (@(Get-ChildItem -LiteralPath $Root -Filter '.install-write-*').Count -eq 0) 'Preflight left temporary files'
""")

    def test_existing_node_with_broken_npm_is_rejected(self):
        self.run_probe(r"""
$NodeMinimumVersion = [version]'22.12.0'
function Get-NodeVersion { [version]'22.14.0' }
function Resolve-CommandPath { 'Invoke-FakeNpm' }
function Invoke-FakeNpm { $global:LASTEXITCODE = 1 }
function Invoke-WingetInstall { throw 'Existing supported Node must not be replaced without evidence' }
Assert-Rejected { Ensure-Node } 'A visible npm.cmd is not proof npm can run'
function Invoke-FakeNpm { $global:LASTEXITCODE = 0; '10.9.2' }
Ensure-Node
""")

    def test_missing_winget_bootstraps_only_current_user(self):
        self.run_probe(r"""
$script:bootstrapped = $false
$script:bootstrapCalls = @()
function Resolve-CommandPath { if ($script:bootstrapped) { 'Invoke-FakeWinget' } }
function Invoke-FakeWinget { $global:LASTEXITCODE = 0; 'v1.12.0' }
function Install-PackageProvider {
    param($Name, $Scope, [switch]$Force)
    Assert-Check ($Name -eq 'NuGet' -and $Scope -eq 'CurrentUser') 'Unsafe NuGet bootstrap'
    $script:bootstrapCalls += 'provider'
}
function Install-Module {
    param($Name, $Repository, $Scope, [switch]$Force)
    Assert-Check ($Name -eq 'Microsoft.WinGet.Client' -and $Repository -eq 'PSGallery') 'Unexpected module source'
    Assert-Check ($Scope -eq 'CurrentUser') 'Do not install system-wide PowerShell modules'
    $script:bootstrapCalls += 'module'
}
function Import-Module { param($Name); $script:bootstrapCalls += 'import' }
function Repair-WinGetPackageManager {
    param([switch]$Latest, [switch]$AllUsers)
    Assert-Check (-not $AllUsers) 'Do not change all users'
    $script:bootstrapped = $true
    $script:bootstrapCalls += 'repair'
}
$resolved = Require-Winget
Assert-Check ($resolved -eq 'Invoke-FakeWinget') 'winget was not re-resolved'
Assert-Check (($script:bootstrapCalls -join ',') -eq 'provider,module,import,repair') 'Bootstrap sequence incomplete'
""")

    def test_new_uv_install_returns_only_the_executable(self):
        self.run_probe(r"""
$script:installed = $false
function Refresh-ProcessPath {}
function Require-Winget { 'Invoke-FakeWinget' }
function Resolve-CommandPath { if ($script:installed) { 'Invoke-FakeUv' } }
function Invoke-FakeUv { $global:LASTEXITCODE = 0; 'uv 0.9.0' }
function Invoke-FakeWinget {
    Assert-Check ($args -contains '--source' -and $args -contains 'winget') 'Source must be explicit'
    $script:installed = $true
    $global:LASTEXITCODE = 0
    'Downloading uv ...'
    'Successfully installed'
}
$resolved = Ensure-Uv
Assert-Check ($resolved -is [string] -and $resolved -eq 'Invoke-FakeUv') 'Installer stdout polluted the uv path'
function Invoke-FakeWinget { $global:LASTEXITCODE = 1603 }
Assert-Rejected { Invoke-WingetInstall -Id 'astral-sh.uv' -Name 'uv' } 'Native failure must stop installation'
""")

    def test_visual_cpp_missing_old_and_installed_states(self):
        self.run_probe(r"""
$script:runtimeRecord = $null
$script:installCount = 0
function Get-ItemProperty { param($LiteralPath, $ErrorAction); $script:runtimeRecord }
function Invoke-WingetInstall {
    param($Id, $Name)
    Assert-Check ($Id -eq 'Microsoft.VCRedist.2015+.x64') 'Wrong runtime architecture'
    $script:installCount++
    $script:runtimeRecord = [pscustomobject]@{ Installed = 1; Version = 'v14.44.35211.0' }
}
Ensure-VisualCppRuntime
Assert-Check ($script:installCount -eq 1) 'A clean PC needs the runtime'
Ensure-VisualCppRuntime
Assert-Check ($script:installCount -eq 1) 'A supported runtime must be preserved'
$script:runtimeRecord.Version = 'v14.0.24215.0'
Ensure-VisualCppRuntime
Assert-Check ($script:installCount -eq 2) 'An obsolete runtime needs upgrading'
function Invoke-WingetInstall { param($Id, $Name) }
$script:runtimeRecord = $null
Assert-Rejected { Ensure-VisualCppRuntime } 'Installer success is not proof of a usable runtime'
""")

    def test_electron_missing_binary_cannot_report_success(self):
        self.run_probe(r"""
$packageDirectory = Join-Path $ElectronDir 'node_modules\electron'
New-Item -ItemType Directory -Path $packageDirectory -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $ElectronDir 'package.json'), '{}')
[IO.File]::WriteAllText((Join-Path $packageDirectory 'package.json'), '{}')
function Ensure-Node {}
function Resolve-CommandPath { 'Invoke-FakeTool' }
function Invoke-FakeTool { $global:LASTEXITCODE = 0 }
Assert-Rejected { Install-ElectronDeps } 'package.json alone must not count as Electron installed'
""")

    def test_electron_repair_includes_dev_scripts_and_restores_environment(self):
        self.run_probe(r"""
$packageDirectory = Join-Path $ElectronDir 'node_modules\electron'
New-Item -ItemType Directory -Path $packageDirectory -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $ElectronDir 'package.json'), '{}')
[IO.File]::WriteAllText((Join-Path $packageDirectory 'install.js'), '// stub')
$env:ELECTRON_SKIP_BINARY_DOWNLOAD = '1'
$originalDirectory = (Get-Location).Path
$script:runtimeChecked = $false
$script:binaryRepaired = $false
function Ensure-Node {}
function Resolve-CommandPath {
    param($Names)
    if ($Names -contains 'npm.cmd') { 'Invoke-FakeNpm' } else { 'Invoke-FakeNode' }
}
function Invoke-FakeNpm {
    Assert-Check ($args -contains '--include=dev') 'NODE_ENV=production must not omit Electron'
    Assert-Check ($args -contains '--ignore-scripts=false') 'Electron postinstall must run'
    Assert-Check (-not $env:ELECTRON_SKIP_BINARY_DOWNLOAD) 'Download suppression must be cleared'
    $global:LASTEXITCODE = 0
}
function Invoke-FakeNode { $script:binaryRepaired = $true; $global:LASTEXITCODE = 0 }
function Test-ElectronRuntime { $script:runtimeChecked = $true }
Install-ElectronDeps
Assert-Check ($script:binaryRepaired -and $script:runtimeChecked) 'Missing binary must be repaired and verified'
Assert-Check ($env:ELECTRON_SKIP_BINARY_DOWNLOAD -eq '1') 'Caller environment was not restored'
Assert-Check ((Get-Location).Path -eq $originalDirectory) 'Working directory was not restored'
function Invoke-FakeNpm { $global:LASTEXITCODE = 1 }
Assert-Rejected { Install-ElectronDeps } 'npm failure must propagate'
Assert-Check ($env:ELECTRON_SKIP_BINARY_DOWNLOAD -eq '1') 'Failure must restore caller environment'
Assert-Check ((Get-Location).Path -eq $originalDirectory) 'Failure must restore working directory'
""")

    def test_existing_broken_venv_is_not_deleted(self):
        self.run_probe(r"""
$VenvDir = Join-Path $Root '.venv'
$PythonVersion = '3.10.15'
New-Item -ItemType Directory -Path $VenvDir | Out-Null
$sentinel = Join-Path $VenvDir 'keep.txt'
[IO.File]::WriteAllText($sentinel, 'existing environment')
function Test-VenvPython { $false }
function Ensure-Uv { throw 'Must not try reinstalling over an existing venv' }
Assert-Rejected { Ensure-Venv } 'Broken existing environments need explicit user action'
Assert-Check ([IO.File]::ReadAllText($sentinel) -eq 'existing environment') 'Existing venv was modified'
""")

    def test_invalid_gpu_config_is_not_coerced_to_true(self):
        self.run_probe(r"""
Assert-Check ((Resolve-PaddleVariant) -eq 'cpu') 'New installs should default to CPU'
[IO.File]::WriteAllText($RuntimeConfig, '{"ocr":{"use_gpu":false}}')
Assert-Check ((Resolve-PaddleVariant) -eq 'cpu') 'Explicit false should select CPU'
[IO.File]::WriteAllText($RuntimeConfig, '{"ocr":{"use_gpu":true}}')
Assert-Check ((Resolve-PaddleVariant) -eq 'gpu') 'Explicit true should select GPU'
[IO.File]::WriteAllText($RuntimeConfig, '{"ocr":{"use_gpu":"false"}}')
Assert-Rejected { Resolve-PaddleVariant } 'A string false must not select GPU on a new PC'
""")


if __name__ == "__main__":
    unittest.main()
