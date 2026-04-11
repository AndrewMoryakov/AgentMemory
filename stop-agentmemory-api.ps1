$script = Join-Path $PSScriptRoot "scripts\run-agentmemory-python.ps1"
& $script -m agentmemory.cli stop-api
exit $LASTEXITCODE
