# ==============================================================================
# RepoScroller - PC2 / CUDA Node Server Process Cleanup Utility
# Forcefully terminates all orphaned llama-server.exe and ollama.exe processes
# ==============================================================================

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[INFO] Re-launching with Administrator privileges to kill system/elevated processes..." -ForegroundColor Yellow
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "   Terminating Zombie / Orphaned LLM & Ollama Processes" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

# 1. Kill via taskkill /F /T
Write-Host "Terminating llama-server.exe..." -ForegroundColor Yellow
taskkill.exe /F /IM "llama-server.exe" /T 2>$null | Out-Null

Write-Host "Terminating ollama.exe..." -ForegroundColor Yellow
taskkill.exe /F /IM "ollama.exe" /T 2>$null | Out-Null
taskkill.exe /F /IM "ollama app.exe" /T 2>$null | Out-Null

# 2. Backup PowerShell kill
Stop-Process -Name "llama-server", "ollama", "ollama app" -Force -ErrorAction SilentlyContinue

Start-Sleep -Seconds 1

# 3. Check remaining processes
$remaining = Get-Process -Name "llama-server", "ollama" -ErrorAction SilentlyContinue

if ($remaining) {
    Write-Host "[WARNING] Some processes could not be terminated:" -ForegroundColor Red
    $remaining | Format-Table Id, ProcessName, WorkingSet64
} else {
    Write-Host "[SUCCESS] All llama-server and ollama processes terminated cleanly!" -ForegroundColor Green
    Write-Host "VRAM and System RAM have been completely reclaimed." -ForegroundColor Green
}

Write-Host ""
Write-Host "Press any key to exit..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
