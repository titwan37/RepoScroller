# ==============================================================================
# RepoScroller - PC2 (CUDA GPU Node) Configuration & Launcher
# Run this script on the PC equipped with NVIDIA RTX 3060 (IP: 192.168.192.9)
# ==============================================================================

param (
    [string]$Model = "snowflake-arctic-embed2:latest",
    [string]$ChatModel = "llama3.1:8b",
    [string]$Port = "11434",
    [switch]$SkipModelPull = $false
)

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "   RepoScroller - PC2 CUDA Inference Server Setup" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Administrator Check for Firewall Configuration
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[INFO] Re-launching with Administrator privileges for Firewall setup..." -ForegroundColor Yellow
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

# 2. NVIDIA GPU & CUDA Detection
Write-Host "[1/5] Checking NVIDIA GPU and CUDA status..." -ForegroundColor Cyan
if (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue) {
    $gpuInfo = nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
    Write-Host "  -> Detected GPU: $gpuInfo" -ForegroundColor Green
} else {
    Write-Host "  -> [WARNING] nvidia-smi not found in PATH. Ensure NVIDIA Drivers and CUDA are installed." -ForegroundColor Yellow
}

# 3. Configure Ollama Environment Variables (Persistent)
Write-Host ""
Write-Host "[2/5] Setting Ollama environment variables for LAN GPU access..." -ForegroundColor Cyan
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:$Port", "Machine")
[Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "24h", "Machine")
[Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL", "4", "Machine")
[Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS", "3", "Machine")
[Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION", "1", "Machine")

$env:OLLAMA_HOST = "0.0.0.0:$Port"
$env:OLLAMA_KEEP_ALIVE = "24h"
$env:OLLAMA_NUM_PARALLEL = "4"
$env:OLLAMA_MAX_LOADED_MODELS = "3"
$env:OLLAMA_FLASH_ATTENTION = "1"

Write-Host "  -> OLLAMA_HOST             = 0.0.0.0:$Port (Listening on all LAN interfaces)" -ForegroundColor Green
Write-Host "  -> OLLAMA_KEEP_ALIVE        = 24h (Model stays resident in VRAM)" -ForegroundColor Green
Write-Host "  -> OLLAMA_NUM_PARALLEL      = 4 (Multi-threaded chunk embedding)" -ForegroundColor Green
Write-Host "  -> OLLAMA_MAX_LOADED_MODELS = 3 (Keep embedding + chat models in VRAM simultaneously)" -ForegroundColor Green
Write-Host "  -> OLLAMA_FLASH_ATTENTION   = 1 (Accelerated CUDA attention kernels)" -ForegroundColor Green

# 4. Inbound Firewall Rule Configuration
Write-Host ""
Write-Host "[3/5] Configuring Windows Firewall inbound rule..." -ForegroundColor Cyan
$existingRule = Get-NetFirewallRule -DisplayName "Ollama LAN API" -ErrorAction SilentlyContinue
if ($existingRule) {
    Write-Host "  -> Firewall rule 'Ollama LAN API' already exists (Active)." -ForegroundColor Green
} else {
    New-NetFirewallRule -DisplayName "Ollama LAN API" `
                        -Description "Allow RepoScroller host to send embedding and inference requests to Ollama" `
                        -Direction Inbound `
                        -LocalPort $Port `
                        -Protocol TCP `
                        -Action Allow | Out-Null
    Write-Host "  -> Created Inbound Firewall Rule: TCP Port $Port [ALLOW]" -ForegroundColor Green
}

# 5. Restart Ollama Service / Background Process
Write-Host ""
Write-Host "[4/5] Restarting Ollama service with new network settings..." -ForegroundColor Cyan
Stop-Process -Name "ollama", "ollama app" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# Check if Ollama is running as a Windows Service or execute server directly
if (Get-Service -Name "ollama" -ErrorAction SilentlyContinue) {
    Restart-Service -Name "ollama"
    Write-Host "  -> Ollama Windows Service restarted." -ForegroundColor Green
} else {
    Start-Process "ollama.exe" -ArgumentList "serve" -WindowStyle Minimized
    Write-Host "  -> Ollama server launched in background." -ForegroundColor Green
}

# Wait for server readiness
$listening = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    try {
        $check = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/tags" -Method Get -TimeoutSec 2 -ErrorAction Stop
        if ($check) { $listening = $true; break }
    } catch {}
}

if ($listening) {
    Write-Host "  -> Ollama server is ONLINE and listening on port $Port." -ForegroundColor Green
} else {
    Write-Host "  -> [WARNING] Ollama server is taking longer to start. Please check terminal." -ForegroundColor Yellow
}

# 6. Pre-pull Embedding Models to VRAM
Write-Host ""
Write-Host "[5/5] Checking embedding model '$Model' and chat model '$ChatModel'..." -ForegroundColor Cyan
if (-not $SkipModelPull) {
    Write-Host "  -> Pulling / verifying '$Model' on GPU..." -ForegroundColor Gray
    ollama pull $Model
    # Also ensure snowflake-arctic-embed is ready if needed
    ollama pull snowflake-arctic-embed:latest
    Write-Host "  -> Pulling / verifying '$ChatModel' on GPU..." -ForegroundColor Gray
    ollama pull $ChatModel
}

# 7. Display LAN IPs and Ready Summary
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "   PC2 CUDA INFERENCE SERVER READY !" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
$ips = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notlike "*Loopback*" -and $_.IPAddress -notlike "169.254*" } | Select-Object -ExpandProperty IPAddress
Write-Host " Your PC2 LAN IP addresses:" -ForegroundColor Cyan
foreach ($ip in $ips) {
    Write-Host "   -> http://${ip}:$Port" -ForegroundColor Yellow
}
Write-Host ""
Write-Host " Configure PC1 (RepoScroller Host) in 'C:\Dev\RepoScroller\.env' with:" -ForegroundColor Gray
Write-Host "   OLLAMA_BASE_URL=http://192.168.192.9:$Port" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
pause
