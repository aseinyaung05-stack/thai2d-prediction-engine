# WMI-safe launcher for the Thai 2D prediction engine (port 8001).
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\')).Path
Set-Location -LiteralPath $PSScriptRoot
$env:PREDICTION_DATABASE_URL = 'postgresql+psycopg2://postgres:postgres@localhost:5432/thai2d'
$env:PREDICTION_API_TOKEN = 'change-me-internal-token'
$env:MAX_WALKFORWARD_STEPS = '460'
& "$root\.venv\Scripts\python.exe" -m uvicorn prediction.api:app --host 127.0.0.1 --port 8001 *> "$root\engine2-server.log"
