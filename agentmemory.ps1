param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$script = Join-Path $PSScriptRoot "scripts\agentmemory.ps1"
& $script @Args
exit $LASTEXITCODE
