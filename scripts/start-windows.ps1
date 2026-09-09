$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe') -or -not (Test-Path -LiteralPath 'frontend\dist\index.html')) {
    throw 'Create the Python venv, install backend/requirements.txt, and run npm --prefix frontend ci followed by npm --prefix frontend run build first.'
}
Write-Host 'AlignFail Dataset Studio: http://localhost:8000'
& '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
