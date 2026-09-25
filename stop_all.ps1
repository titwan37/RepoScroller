# ==============================================================================
# RepoScroller - Process Stopper & Clean Teardown
# Gracefully terminates all running RepoScroller services (Backend, Scanner, Watcher, Sidecar)
# ==============================================================================

param (
    [int]$Port = 8090,
    [switch]$Force = $false
)

Write-Host "================================================================" -ForegroundColor Yellow
Write-Host "   RepoScroller Sovereign Studio - Process Stopper" -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Yellow
Write-Host ""

$killedCount = 0

# 1. Terminate processes listening on FastAPI backend port
Write-Host "[1/3] Checking processes on port $Port (Backend API)..." -ForegroundColor Cyan
try {
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($connections) {
        $pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($procId in $pids) {
            $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($p) {
                Write-Host "  -> Stopping backend process '$($p.ProcessName)' (PID: $procId)..." -ForegroundColor Yellow
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                $killedCount++
            }
        }
    } else {
        Write-Host "  -> Port $Port is clear." -ForegroundColor Green
    }
} catch {
    Write-Host "  -> Port scan notice: $($_.Exception.Message)" -ForegroundColor DarkGray
}

# 2. Terminate all Python / uv processes executing reposcroller commands
Write-Host ""
Write-Host "[2/3] Terminating RepoScroller Python workers (Scanner, Watcher, Sidecar)..." -ForegroundColor Cyan
try {
    $allProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.Name -match "^(python|uv|cmd)\.exe$" -or $_.Name -like "python*") -and
        (
            $_.CommandLine -like "*reposcroller.main*" -or 
            $_.CommandLine -like "*reposcroller.api*" -or 
            $_.CommandLine -like "*start_sidecar.bat*" -or 
            $_.CommandLine -like "*start_watcher.bat*" -or 
            $_.CommandLine -like "*start_scanner.bat*" -or 
            $_.CommandLine -like "*start_backend.bat*"
        )
    }

    foreach ($proc in $allProcesses) {
        if ($proc.ProcessId -ne $PID) {
            Write-Host "  -> Stopping process '$($proc.Name)' (PID: $($proc.ProcessId))..." -ForegroundColor Yellow
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
            $killedCount++
        }
    }
} catch {
    Write-Host "  -> Process query notice: $($_.Exception.Message)" -ForegroundColor DarkGray
}

# 3. Double check for orphaned cmd.exe titled with RepoScroller
Write-Host ""
Write-Host "[3/3] Closing orphaned RepoScroller console windows..." -ForegroundColor Cyan
$cmdProcs = Get-Process -Name "cmd", "WindowsTerminal" -ErrorAction SilentlyContinue
foreach ($cp in $cmdProcs) {
    if ($cp.MainWindowTitle -like "*RepoScroller*") {
        Write-Host "  -> Closing window: '$($cp.MainWindowTitle)' (PID: $($cp.Id))..." -ForegroundColor Yellow
        Stop-Process -Id $cp.Id -Force -ErrorAction SilentlyContinue
        $killedCount++
    }
}

Start-Sleep -Seconds 1

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
if ($killedCount -gt 0) {
    Write-Host "   SUCCESS: $killedCount RepoScroller processes have been cleanly stopped." -ForegroundColor Green
} else {
    Write-Host "   No active RepoScroller processes were found running." -ForegroundColor Green
}
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
