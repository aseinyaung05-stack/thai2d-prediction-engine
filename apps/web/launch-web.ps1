# WMI-safe launcher for the Thai 2D web dashboard (port 3000).
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\')).Path
Set-Location -LiteralPath $PSScriptRoot
$env:NEXT_PUBLIC_API_URL = 'http://localhost:4000'
& "$root\node_modules\next\dist\bin\next" dev -p 3000 *> "$root\web-server.log"
