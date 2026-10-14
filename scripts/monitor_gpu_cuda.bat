@echo off
title RepoScroller - Real-Time NVIDIA CUDA Compute Monitor
echo ================================================================
echo    Monitoring Real-Time NVIDIA GPU / CUDA Compute Utilization
echo    sm: Streaming Multiprocessors (%%) ^| mem: VRAM Bandwidth (%%)
echo    Press Ctrl+C to stop.
echo ================================================================
echo.
nvidia-smi dmon -s u -d 1
pause
