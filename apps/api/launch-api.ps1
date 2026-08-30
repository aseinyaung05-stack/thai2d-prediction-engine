# WMI-safe launcher for the Thai 2D API (port 4000).
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\')).Path
Set-Location -LiteralPath $PSScriptRoot
$env:PORT = '4000'
$env:NODE_ENV = 'development'
$env:DATABASE_URL = 'postgresql://postgres:postgres@localhost:5432/thai2d?schema=public'
$env:ADMIN_USERNAME = 'admin'
$env:ADMIN_PASSWORD = 'change-me-now'
$env:PREDICTION_SERVICE_URL = 'http://localhost:8001'
$env:PREDICTION_API_TOKEN = 'change-me-internal-token'
$env:SYNC_INTERVAL_MINUTES = '55'
& "$root\node_modules\tsx\dist\cli.mjs" src/index.ts *> "$root\api-server.log"
