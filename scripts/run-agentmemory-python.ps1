param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PythonArgs
)

$base = Split-Path -Parent $PSScriptRoot
$python = Join-Path $base ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "AgentMemory virtual environment is missing: $python"
    exit 1
}

& $python @PythonArgs
exit $LASTEXITCODE
