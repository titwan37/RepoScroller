# ==============================================================================
# RepoScroller - PC1 (Host Orchestrator) Launcher
# Launches the FastAPI backend, scanner, watcher, sidecar & tests LAN GPU on PC2
# ==============================================================================

param (
    [switch]$UseWindowsTerminal = $true,
    [switch]$OpenBrowser = $true,
    [switch]$StartScanner = $true,
    [switch]$StartWatcher = $true,
    [switch]$StartSidecar = $true,
    [int]$Port = 8090,
    [int]$Workers = 6,
    [string]$Order = "antichronological"
)

$devPath = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($devPath)) {
    $devPath = "C:\Dev\RepoScroller"
}

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "   RepoScroller Sovereign Studio - PC1 Host Launcher" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " Project Directory : $devPath" -ForegroundColor Gray
Write-Host ""

# 1. Parse .env file for configuration
$envFile = Join-Path $devPath ".env"
$ollamaUrl = "http://192.168.192.9:11434"
$embeddingModel = "snowflake-arctic-embed2:latest"

if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#")) {
            $parts = $line.Split('=', 2)
            if ($parts.Count -eq 2) {
                $k = $parts[0].Trim()
                $v = $parts[1].Split('#')[0].Trim()
                if ($k -eq "OLLAMA_BASE_URL") { $ollamaUrl = $v }
                if ($k -eq "OLLAMA_EMBEDDING_MODEL") { $embeddingModel = $v }
            }
        }
    }
}

# 2. Test Remote PC2 CUDA GPU Connectivity
Write-Host "[1/3] Testing Remote PC2 CUDA Inference Node ($ollamaUrl)..." -ForegroundColor Cyan
$isRemoteReady = $false
try {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $tagsResponse = Invoke-RestMethod -Uri "$ollamaUrl/api/tags" -Method Get -TimeoutSec 3 -ErrorAction Stop
    $sw.Stop()
    
    $modelNames = @()
    if ($tagsResponse.models) {
        $modelNames = $tagsResponse.models | ForEach-Object { $_.name }
    }
    
    Write-Host "  -> [CONNECTED] PC2 CUDA Node is ONLINE (${sw.ElapsedMilliseconds}ms ping)" -ForegroundColor Green
    if ($modelNames -contains $embeddingModel -or ($modelNames | Where-Object { $_.StartsWith($embeddingModel.Split(':')[0]) })) {
        Write-Host "  -> [FOUND] Model '$embeddingModel' is available on PC2." -ForegroundColor Green
    } else {
        Write-Host "  -> [WARNING] Model '$embeddingModel' not found in PC2 model list ($($modelNames -join ', '))." -ForegroundColor Yellow
        Write-Host "     Make sure to run 'setup_pc2_cuda_server.bat' on PC2 to pull it." -ForegroundColor Yellow
    }
    $isRemoteReady = $true
} catch {
    Write-Host "  -> [OFFLINE] Could not connect to PC2 at $ollamaUrl ($($_.Exception.Message))" -ForegroundColor Yellow
    Write-Host "     Verify that PC2 is running Ollama with OLLAMA_HOST=0.0.0.0:11434 and Firewall port 11434 is open." -ForegroundColor Yellow
    Write-Host "     Falling back to local execution or heuristic RAG if unavailable." -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "[2/3] Checking Storage Roots..." -ForegroundColor Cyan
$roots = @(
    "\\SyNAS\xcloud\docs",
    "\\SyNAS\xcloud\LawSuiteRAG",
    "\\SyNAS\CloudSpace\LexSpace",
    "H:\My Drive",
    "L:\My Drive",
    "G:\My Drive"
)
$onlineCount = 0
foreach ($root in $roots) {
    if (Test-Path -LiteralPath $root -ErrorAction SilentlyContinue) {
        Write-Host "  [OK] $root" -ForegroundColor Green
        $onlineCount++
    } else {
        Write-Host "  [--] $root (offline / unmounted)" -ForegroundColor DarkYellow
    }
}
Write-Host "  -> $onlineCount of $($roots.Count) storage repositories accessible." -ForegroundColor Gray

Write-Host ""
Write-Host "[3/3] Orchestrating RepoScroller Services..." -ForegroundColor Cyan

# Delegate to start_all.ps1 with parameters
& (Join-Path $devPath "start_all.ps1") `
    -UseWindowsTerminal:$UseWindowsTerminal `
    -OpenBrowser:$OpenBrowser `
    -StartScanner:$StartScanner `
    -StartWatcher:$StartWatcher `
    -StartSidecar:$StartSidecar `
    -Port $Port `
    -Workers $Workers `
    -Order $Order
