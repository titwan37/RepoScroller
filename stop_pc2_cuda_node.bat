@echo off
title RepoScroller - Stop PC2 CUDA Server
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_pc2_cuda_node.ps1"
pause
