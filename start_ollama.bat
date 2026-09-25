@echo off
chcp 65001 >nul
title RepoScroller - Localhost Ollama Live Activity Console

echo ================================================================
echo    RepoScroller - Localhost Ollama Live Activity Console
echo ================================================================
echo.

set OLLAMA_HOST=127.0.0.1:11434
set OLLAMA_DEBUG=1

REM Verifie si le port 11434 ecoute deja
netstat -ano | findstr :11434 | findstr LISTENING >nul
if %ERRORLEVEL% equ 0 (
    echo [OK] Serveur Ollama actif sur http://127.0.0.1:11434.
    echo [LIVE] Streaming de l'activite et des requetes en direct :
    echo ----------------------------------------------------------------
    powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path '$env:LOCALAPPDATA\Ollama\server.log') { Get-Content -Path '$env:LOCALAPPDATA\Ollama\server.log' -Wait -Tail 30 } else { ollama ps; pause }"
) else (
    echo [INFO] Demarrage du serveur Ollama en mode verbeux (foreground)...
    ollama serve
)

