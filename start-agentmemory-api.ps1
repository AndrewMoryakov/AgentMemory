param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8765
)

$script = Join-Path $PSScriptRoot "scripts\start-agentmemory-api.ps1"
& $script -BindHost $BindHost -Port $Port
exit $LASTEXITCODE
