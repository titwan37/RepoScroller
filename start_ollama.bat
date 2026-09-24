@echo off
chcp 65001 >nul
title RepoScroller - Ollama LLM Server

echo ================================================================
echo    RepoScroller - Ollama LLM Server
echo ================================================================
echo.

set OLLAMA_HOST=127.0.0.1:11434

REM Verifie si le port 11434 ecoute deja
netstat -ano | findstr :11434 | findstr LISTENING >nul
if %ERRORLEVEL% equ 0 (
    echo [OK] Le serveur Ollama est deja actif et operationnel sur le port 11434.
    echo.
    ollama list
    echo.
    echo Cet onglet reste disponible pour vos commandes interactives Ollama.
) else (
    echo [INFO] Demarrage du serveur Ollama...
    ollama serve
)
