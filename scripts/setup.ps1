param([string]$Python = '', [switch]$SkipModel)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not $Python) {
    $Python = (& py -3.12 -c 'import sys; print(sys.executable)')
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12, or pass -Python with a Python 3.11/3.12/3.13 executable path.' }
}
& $Python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
& .\.venv\Scripts\python.exe -m pip install -e '.[test]'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if (-not $SkipModel) {
    & .\.venv\Scripts\python.exe -m seen setup-model
    if ($LASTEXITCODE -ne 0) { throw 'Model setup failed. Retry seen setup-model when connected.' }
}
Write-Host 'Seen is ready. See README.md for capture and UI commands.'
