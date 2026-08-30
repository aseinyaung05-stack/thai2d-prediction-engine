@echo off
rem ============================================================
rem  Thai 2D Prediction Engine - start ALL services (dev)
rem  Windows only. Requires Docker Desktop running (for Postgres).
rem  Open http://localhost:3000 after all windows appear.
rem ============================================================
set ROOT=%~dp0..

echo [1/4] Postgres (docker)...
docker compose -f "%ROOT%\docker-compose.yml" up -d db

echo [2/4] API server -> http://localhost:4000  (log: %ROOT%\api-server.log)
start "thai2d-api" cmd /c "cd /d %ROOT%\apps\api && set PORT=4000 && set NODE_ENV=development && set DATABASE_URL=postgresql://postgres:postgres@localhost:5432/thai2d?schema=public && set ADMIN_USERNAME=admin && set ADMIN_PASSWORD=change-me-now && set PREDICTION_SERVICE_URL=http://localhost:8000 && node ..\node_modules\tsx\dist\cli.mjs src\index.ts > ..\api-server.log 2>&1"

echo [3/4] Prediction engine -> http://localhost:8000  (log: %ROOT%\engine-server.log)
start "thai2d-engine" cmd /c "cd /d %ROOT%\services\prediction && set PREDICTION_DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/thai2d && set PREDICTION_API_TOKEN=change-me-internal-token && set MAX_WALKFORWARD_STEPS=110 && ..\..\.venv\Scripts\python.exe -m uvicorn prediction.api:app --host 127.0.0.1 --port 8000 > ..\engine-server.log 2>&1"

echo [4/4] Web dashboard -> http://localhost:3000  (log: %ROOT%\web-server.log)
start "thai2d-web" cmd /c "cd /d %ROOT%\apps\web && set NEXT_PUBLIC_API_URL=http://localhost:4000 && node ..\node_modules\next\dist\bin\next dev -p 3000 > ..\web-server.log 2>&1"

timeout /t 12 >nul
echo.
echo All services launching...
echo   Dashboard : http://localhost:3000
echo   API       : http://localhost:4000/api/health
echo   Engine    : http://localhost:8000/health
echo.
echo To pull fresh results:  POST http://localhost:4000/api/sync?provider=thai2d^&days=140
echo   (Basic auth admin / change-me-now)
pause
