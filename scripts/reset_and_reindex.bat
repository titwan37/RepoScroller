@echo off
title RepoScroller - Reset and Re-index
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0reset_and_reindex.ps1" %*
