@echo off
title RepoScroller - PC2 CUDA GPU Server
echo ================================================================
echo    RepoScroller - PC2 CUDA GPU Server Launcher (RTX 3060)
echo ================================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_pc2_cuda_node.ps1" %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] PC2 CUDA Server encountered an issue.
    pause
)
