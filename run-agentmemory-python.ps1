param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PythonArgs
)

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "AgentMemory virtual environment is missing: $python"
    exit 1
}

& $python @PythonArgs
exit $LASTEXITCODE
