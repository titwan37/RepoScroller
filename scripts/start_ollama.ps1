# ==============================================================================
# RepoScroller - Localhost Ollama Live Rich Color Activity Console
# ==============================================================================

$Host.UI.RawUI.WindowTitle = "RepoScroller - Localhost Ollama Live Activity Console (PC1)"

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "   RepoScroller - Localhost Ollama Live Activity Console" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " Host Endpoint   : http://127.0.0.1:11434" -ForegroundColor Gray

$logPath = "$env:LOCALAPPDATA\Ollama\server.log"

# 1. Probe local Ollama status & models
try {
    $res = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -Method Get -TimeoutSec 2 -ErrorAction Stop
    $models = if ($res.models) { ($res.models | ForEach-Object { $_.name }) -join ", " } else { "(no models loaded)" }
    Write-Host " Active Server   : [ONLINE] Ollama 11434" -ForegroundColor Green
    Write-Host " Local Models    : $models" -ForegroundColor DarkCyan
} catch {
    Write-Host " Active Server   : [STARTING] Launching background Ollama instance..." -ForegroundColor Yellow
    Start-Process "ollama.exe" -ArgumentList "serve" -WindowStyle Minimized
    Start-Sleep -Seconds 2
}

Write-Host ""
Write-Host " Live Request Stream (Colorized Telemetry):" -ForegroundColor White
Write-Host " ----------------------------------------------------------------" -ForegroundColor DarkGray

if (-not (Test-Path $logPath)) {
    Write-Host " [NOTICE] Log file $logPath not found yet. Waiting for server logs..." -ForegroundColor Yellow
    while (-not (Test-Path $logPath)) {
        Start-Sleep -Seconds 1
    }
}

# 2. Continuous real-time color stream
Get-Content -Path $logPath -Wait -Tail 40 | ForEach-Object {
    $line = $_
    if ($line -match '\[GIN\]\s+\S+\s+-\s+(\d{2}:\d{2}:\d{2})\s+\|\s+(\d{3})\s+\|\s+([0-9\.\w\s]+)\|\s+\S+\s+\|\s+(\w+)\s+"([^"]+)"') {
        $timeStr = $matches[1]
        $code = [int]$matches[2]
        $lat = $matches[3].Trim()
        $method = $matches[4]
        $endpoint = $matches[5]

        $codeColor = if ($code -eq 200) { "Green" } elseif ($code -eq 404) { "Yellow" } else { "Red" }
        $icon = if ($endpoint -like "*chat*") { "[CHAT]" } elseif ($endpoint -like "*embed*") { "[EMBED]" } else { "[API]" }
        $endpointColor = if ($endpoint -like "*chat*") { "Cyan" } elseif ($endpoint -like "*embed*") { "Magenta" } else { "White" }

        Write-Host "[$timeStr] " -ForegroundColor DarkGray -NoNewline
        Write-Host "[$code] " -ForegroundColor $codeColor -NoNewline
        Write-Host "$icon " -ForegroundColor $endpointColor -NoNewline
        Write-Host "$method $endpoint " -ForegroundColor White -NoNewline
        Write-Host "($lat)" -ForegroundColor DarkYellow
    }
    elseif ($line -match 'level=(\w+)\s+msg="([^"]+)"') {
        $level = $matches[1].ToUpper()
        $msg = $matches[2]
        $levelColor = if ($level -eq "ERROR") { "Red" } elseif ($level -eq "WARN") { "Yellow" } else { "DarkGray" }
        Write-Host "[SYSTEM] " -ForegroundColor DarkCyan -NoNewline
        Write-Host "[$level] " -ForegroundColor $levelColor -NoNewline
        Write-Host "$msg" -ForegroundColor Gray
    }
    elseif ($line.Trim().Length -gt 0) {
        Write-Host "$line" -ForegroundColor DarkGray
    }
}
