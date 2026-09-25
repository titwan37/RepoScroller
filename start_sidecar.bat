@echo off
chcp 65001 >nul
title RepoScroller - Knowledge Base Sidecar Worker (Vectors and Graph)

echo ================================================================
echo    RepoScroller - Knowledge Base Sidecar and GraphRAG Worker
echo ================================================================
echo  Embedding Model: snowflake-arctic-embed:latest
echo  Mode:            Continuous Daemon and Asynchronous CDC Queue
echo ================================================================

echo.

cd /d "%~dp0"
echo [%TIME%] Demarrage du worker Knowledge Base Sidecar...
uv run python -m reposcroller.main sidecar --poll-interval 3.0 %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo [%TIME%] [ERREUR] Le worker s'est arrete avec le code %ERRORLEVEL%.
    pause
)
