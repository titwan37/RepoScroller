@echo off
title MemoryBlast CLI
echo ================================================================
echo    MemoryBlast CLI - Sovereign Memory Manager
echo ================================================================
echo.
if exist "C:\Dev\MemoryBlast\target\debug\memoryblast.exe" (
    "C:\Dev\MemoryBlast\target\debug\memoryblast.exe" --cli
) else if exist "C:\Dev\MemoryBlast\target\release\memoryblast.exe" (
    "C:\Dev\MemoryBlast\target\release\memoryblast.exe" --cli
) else (
    echo [ERROR] memoryblast.exe not found at C:\Dev\MemoryBlast\target\debug\memoryblast.exe
    pause
)