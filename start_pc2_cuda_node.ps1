# ==============================================================================
# RepoScroller - PC2 (CUDA GPU Node) Daily Launcher & Monitor
# Run this on PC2 (NVIDIA RTX 3060) to keep Ollama GPU inference live & warmed up
# ==============================================================================

param (
    [string]$Model = "snowflake-arctic-embed2:latest",
    [string]$Port = "11434"
)

$Host.UI.RawUI.WindowTitle = "RepoScroller - PC2 CUDA GPU Server (RTX 3060)"

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "   RepoScroller - PC2 CUDA GPU Inference Node Launcher" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. GPU & CUDA Detection
Write-Host "[1/4] Checking NVIDIA RTX 3060 GPU..." -ForegroundColor Cyan
if (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue) {
    $gpuName = nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
    Write-Host "  -> GPU: $gpuName" -ForegroundColor Green
} else {
    Write-Host "  -> [WARNING] nvidia-smi not in PATH." -ForegroundColor Yellow
}

# 2. Environment Variables for the session
$env:OLLAMA_HOST = "0.0.0.0:$Port"
$env:OLLAMA_KEEP_ALIVE = "24h"
$env:OLLAMA_NUM_PARALLEL = "4"
$env:OLLAMA_FLASH_ATTENTION = "1"

# 3. Check / Start Ollama Server
Write-Host ""
Write-Host "[2/4] Checking Ollama Server on port $Port..." -ForegroundColor Cyan
$isListening = $false
try {
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/tags" -Method Get -TimeoutSec 2 -ErrorAction Stop
    $isListening = $true
} catch {
    $isListening = $false
}

if (-not $isListening) {
    Write-Host "  -> Starting Ollama server..." -ForegroundColor Yellow
    if (Get-Service -Name "ollama" -ErrorAction SilentlyContinue) {
        Start-Service -Name "ollama" -ErrorAction SilentlyContinue
    } else {
        Start-Process "ollama.exe" -ArgumentList "serve" -WindowStyle Minimized
    }
    
    # Wait for server ready
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 1
        try {
            $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/tags" -Method Get -TimeoutSec 2 -ErrorAction Stop
            $isListening = $true
            break
        } catch {}
    }
}

if ($isListening) {
    Write-Host "  -> Ollama Server is ONLINE (0.0.0.0:$Port)" -ForegroundColor Green
} else {
    Write-Host "  -> [ERROR] Failed to start Ollama. Ensure Ollama is installed." -ForegroundColor Red
    pause
    exit 1
}

# 4. Pre-warm Embedding Model in VRAM
Write-Host ""
Write-Host "[3/4] Pre-warming embedding model '$Model' into VRAM..." -ForegroundColor Cyan
try {
    $warmupPayload = @{
        model = $Model
        input = "RepoScroller sovereign LAN CUDA embedding node warm-up probe"
        keep_alive = "24h"
    } | ConvertTo-Json
    
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $res = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/embed" -Method Post -Body $warmupPayload -ContentType "application/json" -TimeoutSec 30
    $sw.Stop()
    
    if ($res.embeddings) {
        $dim = $res.embeddings[0].Count
        Write-Host "  -> Model loaded into VRAM ($dim-dim vectors, warm-up took $($sw.ElapsedMilliseconds)ms)" -ForegroundColor Green
    }
} catch {
    Write-Host "  -> Warm-up notice: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "     If the model is not pulled yet, run 'setup_pc2_cuda_server.bat' first." -ForegroundColor Gray
}

# 5. Live Node Status Summary
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "   PC2 CUDA GPU NODE IS ACTIVE & READY FOR PC1 REQUESTS" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
$ips = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notlike "*Loopback*" -and $_.IPAddress -notlike "169.254*" } | Select-Object -ExpandProperty IPAddress
Write-Host " Endpoints listening on LAN:" -ForegroundColor Cyan
foreach ($ip in $ips) {
    Write-Host "   -> http://${ip}:$Port" -ForegroundColor Yellow
}
Write-Host ""
Write-Host " Active Models in VRAM:" -ForegroundColor Cyan
if (Get-Command ollama.exe -ErrorAction SilentlyContinue) {
    ollama ps
}
Write-Host ""
Write-Host " Press [Ctrl+C] to exit or leave this window open." -ForegroundColor Gray
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""

# Keep alive loop displaying live status every 60s
while ($true) {
    Start-Sleep -Seconds 60
}
