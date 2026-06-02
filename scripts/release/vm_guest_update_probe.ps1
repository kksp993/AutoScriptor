param(
  [string]$InstallRoot = "$env:USERPROFILE\Documents\AutoScriptorUpdateTest",
  [string]$OutPath = "\\VBOXSVR\release\logs\vm_update_100_to_101\backend-direct-after-update.json",
  [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

function Wait-WebUi($Uri, [int]$TimeoutSeconds) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $attempts = 0
  $lastError = ""
  while ((Get-Date) -lt $deadline) {
    $attempts += 1
    try {
      $resp = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 5
      return [ordered]@{
        Ok = $true
        Attempts = $attempts
        StatusCode = [int]$resp.StatusCode
        LastError = $lastError
      }
    } catch {
      $lastError = $_.Exception.Message
      Start-Sleep -Seconds 2
    }
  }
  return [ordered]@{
    Ok = $false
    Attempts = $attempts
    StatusCode = $null
    LastError = $lastError
  }
}

function Write-Json($Path, $Object) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
  $Object | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
}

$engine = Join-Path $InstallRoot "backend\autoscriptor-engine.exe"
$result = [ordered]@{
  Time = (Get-Date).ToString("o")
  InstallRoot = $InstallRoot
  Engine = $engine
  EngineExists = Test-Path -LiteralPath $engine -PathType Leaf
  ProcessId = $null
  WebUi = $null
  Error = ""
}

try {
  foreach ($name in @("autoscriptor-engine.exe", "$([char]0x9020)$([char]0x7b14).exe")) {
    try { & "$env:SystemRoot\System32\taskkill.exe" /IM $name /T /F 2>$null | Out-Null } catch {}
  }
  if (-not $result.EngineExists) {
    throw "Missing engine: $engine"
  }
  $proc = Start-Process -FilePath $engine -ArgumentList "--electron" -WorkingDirectory (Split-Path -Parent $engine) -PassThru
  $result.ProcessId = $proc.Id
  $result.WebUi = Wait-WebUi "http://127.0.0.1:5000" $TimeoutSeconds
} catch {
  $result.Error = $_.Exception.Message
} finally {
  Write-Json $OutPath $result
}

if (-not $result.WebUi -or -not $result.WebUi.Ok) {
  exit 1
}
