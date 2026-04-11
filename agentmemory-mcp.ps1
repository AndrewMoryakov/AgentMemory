$script = Join-Path $PSScriptRoot "scripts\run-agentmemory-mcp.ps1"
& $script
exit $LASTEXITCODE
