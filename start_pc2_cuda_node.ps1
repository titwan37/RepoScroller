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

# Parse .env if present
$envFile = Join-Path $PSScriptRoot ".env"
$chatModel = "llama3.1:8b"

if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#")) {
            $parts = $line.Split('=', 2)
            if ($parts.Count -eq 2) {
                $k = $parts[0].Trim()
                $v = $parts[1].Trim().Split('#')[0].Trim()
                if ($k -eq "OLLAMA_EMBEDDING_MODEL") { $Model = $v }
                if ($k -eq "OLLAMA_MODEL_PC2") { $chatModel = $v }
            }
        }
    }
}

# 1. GPU & CUDA Detection
Write-Host "[1/4] Checking NVIDIA RTX 3060 GPU..." -ForegroundColor Cyan
if (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue) {
    $gpuName = nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
    Write-Host "  -> GPU: $gpuName" -ForegroundColor Green
} else {
    Write-Host "  -> [WARNING] nvidia-smi not in PATH." -ForegroundColor Yellow
}

# 2. Environment Variables for the session and User scope
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:$Port", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "24h", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL", "4", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS", "3", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION", "1", "User")

$env:OLLAMA_HOST = "0.0.0.0:$Port"
$env:OLLAMA_KEEP_ALIVE = "24h"
$env:OLLAMA_NUM_PARALLEL = "4"
$env:OLLAMA_MAX_LOADED_MODELS = "3"
$env:OLLAMA_FLASH_ATTENTION = "1"

# 3. Check / Restart Ollama Server to ensure multi-model VRAM settings take effect
Write-Host ""
Write-Host "[2/4] Ensuring Ollama Server is running with OLLAMA_MAX_LOADED_MODELS=3..." -ForegroundColor Cyan

# Stop old instances so they inherit the new environment variables
Stop-Process -Name "ollama", "ollama app" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

Write-Host "  -> Launching Ollama server (0.0.0.0:$Port)..." -ForegroundColor Yellow
Start-Process "ollama.exe" -ArgumentList "serve" -WindowStyle Minimized

# Wait for server ready
$isListening = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/tags" -Method Get -TimeoutSec 2 -ErrorAction Stop
        $isListening = $true
        break
    } catch {}
}

if ($isListening) {
    Write-Host "  -> Ollama Server is ONLINE (0.0.0.0:$Port, Max Loaded Models: 3)" -ForegroundColor Green
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
        model      = $Model
        input      = "RepoScroller sovereign LAN CUDA embedding node warm-up probe"
        keep_alive = "24h"
        options    = @{
            num_ctx = 2048
        }
    } | ConvertTo-Json -Depth 5
    
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $res = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/embed" -Method Post -Body $warmupPayload -ContentType "application/json" -TimeoutSec 120
    $sw.Stop()
    
    if ($res.embeddings) {
        $dim = $res.embeddings[0].Count
        Write-Host "  -> Embedding model loaded ($dim-dim, warm-up took $($sw.ElapsedMilliseconds)ms)" -ForegroundColor Green
    }
} catch {
    Write-Host "  -> Embedding warm-up notice: $($_.Exception.Message)" -ForegroundColor Yellow
}

# 5. Pre-warm Chat Model into VRAM
Write-Host ""
Write-Host "[4/4] Pre-warming chat model '$chatModel' into VRAM..." -ForegroundColor Cyan
try {
    $warmupPayloadChat = @{
        model      = $chatModel
        messages   = @(
            @{ role = "user"; content = "ping" }
        )
        keep_alive = "24h"
        stream     = $false
        options    = @{
            num_ctx = 2048
        }
    } | ConvertTo-Json -Depth 5

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/chat" -Method Post -Body $warmupPayloadChat -ContentType "application/json" -TimeoutSec 120
    $sw.Stop()
    Write-Host "  -> Chat model '$chatModel' loaded into VRAM (took $($sw.ElapsedMilliseconds)ms)" -ForegroundColor Green
} catch {
    Write-Host "  -> Chat warm-up notice: $($_.Exception.Message)" -ForegroundColor Yellow
}

# 6. Live Node Status Summary
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

# Monitor loop displaying active VRAM models periodically
while ($true) {
    Start-Sleep -Seconds 60
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Active Models in VRAM:" -ForegroundColor Cyan
    if (Get-Command ollama.exe -ErrorAction SilentlyContinue) {
        ollama ps
    }
}