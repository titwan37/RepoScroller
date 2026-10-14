@echo off
title RepoScroller - Cleanup Zombie LLM Processes
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0cleanup_zombie_servers.ps1"
