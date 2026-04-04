param()

$base = $PSScriptRoot
$pidFile = Join-Path $base 'data\agentmemory-api.pid'

if (-not (Test-Path $pidFile)) {
    Write-Output 'AgentMemory API PID file not found.'
    exit 0
}

$processId = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue
if ($processId -and (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
    Stop-Process -Id $processId -Force
    Write-Output "Stopped AgentMemory API process $processId"
} else {
    Write-Output 'AgentMemory API process is not running.'
}

Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
