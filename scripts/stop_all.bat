@echo off
title RepoScroller - Stop All Services
echo ================================================================
echo    RepoScroller - Stopping All Running Services
echo ================================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_all.ps1" %*

echo.
pause
