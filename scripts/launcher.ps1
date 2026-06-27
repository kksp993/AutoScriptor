param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AppArgs
)

$RunScript = Join-Path $PSScriptRoot "run.ps1"
& $RunScript @AppArgs
exit $LASTEXITCODE
