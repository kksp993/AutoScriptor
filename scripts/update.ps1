param()

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
$Root = (Resolve-Path -Path (Join-Path $ScriptDir "..")).Path
$SafeRoot = $Root.Replace("\", "/")
$TargetBranch = "main"

function Find-Git {
    $names = @("git.exe", "git")
    foreach ($name in $names) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $cmd) {
            return $cmd.Source
        }
    }
    return $null
}

$Git = Find-Git
if (-not $Git) {
    throw "git not found. Install Git for Windows first."
}

if (-not (Test-Path -LiteralPath (Join-Path $Root ".git") -PathType Container)) {
    throw "Current directory is not a Git working tree: $Root"
}

function Invoke-GitText {
    param([string[]]$GitArgs)
    $output = & $Git -c "safe.directory=$SafeRoot" @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArgs -join ' ') failed: $output"
    }
    return $output
}

$status = @(Invoke-GitText @("status", "--porcelain"))
if (($status -join "").Trim().Length -gt 0) {
    throw "Working tree has local changes. Commit or clean them before running scripts\update.bat."
}

$branch = (Invoke-GitText @("rev-parse", "--abbrev-ref", "HEAD") | Select-Object -First 1).Trim()
if (-not $branch -or $branch -eq "HEAD") {
    throw "Detached HEAD is not supported by scripts\update.bat."
}

Write-Host "Fetching origin/$TargetBranch ..."
Invoke-GitText @("fetch", "origin", $TargetBranch) | Out-Null

$countText = (Invoke-GitText @("rev-list", "--left-right", "--count", "HEAD...origin/$TargetBranch") | Select-Object -First 1).Trim()
$counts = $countText -split "\s+"
if ($counts.Count -ne 2) {
    throw "git rev-list returned unexpected ahead/behind output: $countText"
}
$ahead = [int]$counts[0]
$behind = [int]$counts[1]

if ($ahead -gt 0 -and $behind -gt 0) {
    throw "Local branch '$branch' and origin/$TargetBranch have diverged: local ahead $ahead commit(s), behind $behind. Resolve with Git manually."
}

if ($behind -eq 0) {
    if ($ahead -gt 0) {
        Write-Host "Already latest: $branch is ahead of origin/$TargetBranch by $ahead commit(s)."
    } else {
        Write-Host "Already latest: $branch is aligned with origin/$TargetBranch."
    }
    exit 0
}

Write-Host "Pulling origin/$TargetBranch with fast-forward only ..."
Invoke-GitText @("pull", "--ff-only", "origin", $TargetBranch) | Out-Null

$commit = (Invoke-GitText @("rev-parse", "--short", "HEAD") | Select-Object -First 1).Trim()
Write-Host "Update complete: $branch@$commit from origin/$TargetBranch"
Write-Host "If dependencies changed, run scripts\install.bat before scripts\run.bat."
exit 0
