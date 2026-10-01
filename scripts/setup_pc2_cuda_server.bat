@echo off
title RepoScroller - PC2 CUDA Setup & Launcher
echo ================================================================
echo    RepoScroller - PC2 CUDA GPU Node Setup (NVIDIA RTX 3060)
echo ================================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_pc2_cuda_server.ps1"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] An error occurred during setup.
    pause
)
