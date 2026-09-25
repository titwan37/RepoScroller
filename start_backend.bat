@echo off
chcp 65001 >nul
title RepoScroller - Backend API and Web Dashboard (:8090)

echo ================================================================
echo    RepoScroller - Backend API and Web Dashboard Service

echo ================================================================
echo  Local Endpoint:  http://127.0.0.1:8090
echo  Documentation:   http://127.0.0.1:8090/docs
echo  Diagnostics:     http://127.0.0.1:8090/api/v1/diagnostics/health
echo ================================================================
echo.

cd /d "%~dp0"
echo [%TIME%] Demarrage du serveur FastAPI / Uvicorn sur 127.0.0.1:8090...
uv run python -m reposcroller.main serve --host 127.0.0.1 --port 8090 --reload

if %ERRORLEVEL% neq 0 (
    echo.
    echo [%TIME%] [ERREUR] Le serveur s'est arrete avec le code %ERRORLEVEL%.
    pause
)
