param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$base = $PSScriptRoot
$venvPython = Join-Path $base '.venv\Scripts\python.exe'
$script = Join-Path $base 'agentmemory.py'

if (Test-Path $venvPython) {
    & $venvPython $script @Args
    exit $LASTEXITCODE
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    & python $script @Args
    exit $LASTEXITCODE
}

& py -3.13 $script @Args
exit $LASTEXITCODE
