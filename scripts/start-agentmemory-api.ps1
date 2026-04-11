param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8765
)

$base = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $base 'data\agentmemory-api.pid'
$logFile = Join-Path $base 'data\agentmemory-api.log'
$errorFile = Join-Path $base 'data\agentmemory-api.err.log'
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

if (Test-Path $pidFile) {
    $existingPid = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue
    if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        $listening = Get-NetTCPConnection -OwningProcess $existingPid -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalPort -eq $Port -and ($_.LocalAddress -eq $BindHost -or $_.LocalAddress -eq '0.0.0.0' -or $_.LocalAddress -eq '::') }
        if ($listening) {
            Write-Output "AgentMemory API is already running with PID $existingPid on $BindHost`:$Port"
            exit 0
        }

        Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }
}

$env:AGENTMEMORY_API_HOST = $BindHost
$env:AGENTMEMORY_API_PORT = [string]$Port
$env:AGENTMEMORY_OWNER_PROCESS = '1'
$result = & $python -m agentmemory.cli start-api --host $BindHost --port $Port 2>&1
$exitCode = $LASTEXITCODE
if ($result) {
    $result | ForEach-Object { Write-Output $_ }
}
exit $exitCode
