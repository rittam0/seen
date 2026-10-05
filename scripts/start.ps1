param([string]$Data = '', [int]$Port = 8765, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $workspace
if (-not $Data) { $Data = Join-Path $workspace 'demo-data' }
$dataDirectory = [System.IO.Path]::GetFullPath($Data)
$pythonExecutable = Join-Path $workspace '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    Write-Host 'Preparing the Python environment...'
    & (Join-Path $PSScriptRoot 'setup.ps1') -SkipModel
}
if (-not (Test-Path -LiteralPath $pythonExecutable)) { throw 'Python setup failed. See README.md for setup instructions.' }
New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $dataDirectory 'models'))) {
    Write-Host 'Downloading the local search model (first launch only)...'
    & $pythonExecutable -m seen --data $dataDirectory setup-model
    if ($LASTEXITCODE -ne 0) { throw 'Model download failed. Connect to the internet and try again.' }
}
$url = "http://127.0.0.1:$Port"
function Read-SeenStatus {
    try { return Invoke-RestMethod -Uri "$url/api/status" -TimeoutSec 2 }
    catch { return $null }
}
$status = Read-SeenStatus
$server = $null
if (-not $status) {
    Write-Host 'Starting Seen...'
    $server = Start-Process -FilePath $pythonExecutable -ArgumentList @('-m', 'seen', '--data', ('"{0}"' -f $dataDirectory), 'ui', '--port', $Port) -WorkingDirectory $workspace -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dataDirectory 'ui.log') -RedirectStandardError (Join-Path $dataDirectory 'ui-error.log') -PassThru
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 250
        $status = Read-SeenStatus
        if ($status) { break }
        if ($server.HasExited) { break }
    }
}
if (-not $status -or -not $status.token) {
    throw "Seen did not start. Check $dataDirectory\ui-error.log. Port $Port may be in use."
}
if ($status.data_directory -and $status.data_directory -ne $dataDirectory) {
    throw "Another Seen instance uses port $Port with $($status.data_directory). Choose another -Port or use that instance."
}
if (-not $status.worker_online) {
    Write-Host 'Starting the capture worker (respecting your saved pause setting)...'
    $capture = Start-Process -FilePath $pythonExecutable -ArgumentList @('-m', 'seen', '--data', ('"{0}"' -f $dataDirectory), 'capture') -WorkingDirectory $workspace -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dataDirectory 'capture.log') -RedirectStandardError (Join-Path $dataDirectory 'capture-error.log') -PassThru
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 250
        $status = Read-SeenStatus
        if ($status.worker_online) { break }
        if ($capture.HasExited) { break }
    }
    if (-not $status.worker_online) { throw "The search UI is running, but capture could not start. Check $dataDirectory\capture-error.log." }
}
Write-Host "Seen is ready: $url"
Write-Host "Data: $dataDirectory"
Write-Host 'Use the capture status button to pause or resume. Closing the browser leaves Seen running.'
if (-not $NoBrowser) { Start-Process $url -WindowStyle Hidden }
