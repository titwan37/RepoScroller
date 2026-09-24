@echo off
chcp 65001 >nul
title RepoScroller - Parallel Scanner Pool (x6 Threads)

echo ================================================================
echo    RepoScroller - Parallel Scanner Pool Engine
echo ================================================================
echo  Threads Concurrents: 6 (1 par referentiel SMB / Google Drive)
echo  Ordre Traversale:    Anti-chronologique (fichiers recents d'abord)
echo ================================================================
echo.

cd /d "%~dp0"
echo [%TIME%] Lancement du scan batch parallele...
uv run python -m reposcroller.main scan --workers 6 --order antichronological

echo.
echo [%TIME%] Scan termine.
pause
