param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$base = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $base '.venv\Scripts\python.exe'

if (Test-Path $venvPython) {
    & $venvPython -m agentmemory @Args
    exit $LASTEXITCODE
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    & python -m agentmemory @Args
    exit $LASTEXITCODE
}

& py -3.13 -m agentmemory @Args
exit $LASTEXITCODE
