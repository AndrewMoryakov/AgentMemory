param()

$base = Split-Path -Parent $PSScriptRoot
$python = Join-Path $base '.venv\Scripts\python.exe'
$envFile = Join-Path $base '.env'

if ((-not $env:OPENROUTER_API_KEY) -and (Test-Path $envFile)) {
    Get-Content -LiteralPath $envFile | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
        $parts = $_.Split('=', 2)
        if ($parts[0].Trim() -eq 'OPENROUTER_API_KEY' -and -not $env:OPENROUTER_API_KEY) {
            $env:OPENROUTER_API_KEY = $parts[1].Trim().Trim('"').Trim("'")
        }
    }
}

& $python -m agentmemory.mcp
exit $LASTEXITCODE
