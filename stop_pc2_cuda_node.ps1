# ==============================================================================
# RepoScroller - PC2 CUDA Node Stopper
# Stops Ollama server / service on PC2 to free VRAM
# ==============================================================================

Write-Host "================================================================" -ForegroundColor Yellow
Write-Host "   Stopping Ollama CUDA Server on PC2..." -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Yellow

$stopped = $false
if (Get-Service -Name "ollama" -ErrorAction SilentlyContinue) {
    Stop-Service -Name "ollama" -Force -ErrorAction SilentlyContinue
    $stopped = $true
}

$ollamaProcs = Get-Process -Name "ollama", "ollama app" -ErrorAction SilentlyContinue
if ($ollamaProcs) {
    $ollamaProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    $stopped = $true
}

if ($stopped) {
    Write-Host "  -> Ollama processes stopped. GPU VRAM freed." -ForegroundColor Green
} else {
    Write-Host "  -> Ollama was not running." -ForegroundColor Gray
}

Write-Host "================================================================" -ForegroundColor Yellow
Start-Sleep -Seconds 2
