@echo off
title RepoScroller - PC1 Host Launcher
echo ================================================================
echo    RepoScroller - PC1 Host Launcher (LAN CUDA Acceleration)
echo ================================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_pc1_host.ps1" %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Launcher encountered an issue.
    pause
)
