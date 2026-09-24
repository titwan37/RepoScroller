@echo off
chcp 65001 >nul
title RepoScroller - Real-Time Polling Watcher

echo ================================================================
echo    RepoScroller - Real-Time Watchdog PollingObserver Daemon
echo ================================================================
echo  Surveillance continue des 6 referentiels montes
echo  Appuyez sur Ctrl+C pour arreter le watcher
echo ================================================================
echo.

cd /d "%~dp0"
echo [%TIME%] Demarrage du watcher continu...
uv run python -m reposcroller.main watch

if %ERRORLEVEL% neq 0 (
    echo.
    echo [%TIME%] [ERREUR] Le watcher s'est arrete avec le code %ERRORLEVEL%.
    pause
)
