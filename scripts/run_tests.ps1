param(
    [int]$PerFileTimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python -ErrorAction Stop).Source
& $python (Join-Path $PSScriptRoot 'run_tests.py') --timeout $PerFileTimeoutSeconds
exit $LASTEXITCODE
