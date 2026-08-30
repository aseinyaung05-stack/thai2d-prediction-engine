@echo off
rem Local development launcher for the Thai 2D prediction engine.
cd /d "%~dp0"
set PREDICTION_DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/thai2d
set PREDICTION_API_TOKEN=change-me-internal-token
set MAX_WALKFORWARD_STEPS=460
"..\.venv\Scripts\python.exe" -m uvicorn prediction.api:app --host 127.0.0.1 --port 8001 > "..\engine2-server.log" 2>&1
