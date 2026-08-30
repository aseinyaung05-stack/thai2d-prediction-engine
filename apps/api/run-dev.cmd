@echo off
cd /d "%~dp0"
set PORT=4000
set NODE_ENV=development
set DATABASE_URL=postgresql://postgres:postgres@localhost:5432/thai2d?schema=public
set ADMIN_USERNAME=admin
set ADMIN_PASSWORD=change-me-now
set PREDICTION_SERVICE_URL=http://localhost:8001
set PREDICTION_API_TOKEN=change-me-internal-token
set SYNC_INTERVAL_MINUTES=55
"C:\Program Files\nodejs\node.exe" "C:\Users\Khun Myoe Oo\OneDrive\Documents\Default Project\node_modules\tsx\dist\cli.mjs" src/index.ts > "C:\Users\Khun Myoe Oo\OneDrive\Documents\Default Project\api-server.log" 2>&1
