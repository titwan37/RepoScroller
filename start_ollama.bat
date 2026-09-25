@echo off
chcp 65001 >nul
title RepoScroller - Localhost Ollama Live Activity Console

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_ollama.ps1"



