# RepoScroller - Reset Dataset & Re-Index from Scratch
param (
    [switch]$NoBackup = $false,
    [switch]$StartAll = $true,
    [int]$Workers = 6,
    [string]$Order = "antichronological"
)

$devPath = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($devPath)) {
    $devPath = "C:\Dev\RepoScroller"
}

Set-Location $devPath

Write-Host "================================================================" -ForegroundColor Red
Write-Host "   RepoScroller - Ledger Dataset Reset & Re-Indexing Engine" -ForegroundColor Red
Write-Host "================================================================" -ForegroundColor Red
Write-Host " This will reset the SQLite WAL ledger, FTS5 index, knowledge" -ForegroundColor Yellow
Write-Host " graph, and chunk embeddings to re-index all files with pristine" -ForegroundColor Yellow
Write-Host " UTF-8 and OpenXML .docx extraction." -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Red
Write-Host ""

# 1. Reset Database & Qdrant/SQLite Collections
$resetArgs = @("run", "python", "-m", "reposcroller.main", "reset", "-y")
if ($NoBackup) {
    $resetArgs += "--no-backup"
}

Write-Host "[1/3] Resetting database ledger and vector collections..." -ForegroundColor Cyan
& uv @resetArgs

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERREUR] Le reset de la base a echoue." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[2/3] Base de donnees reinitialisee avec succes !" -ForegroundColor Green
Write-Host ""

# 2. Launching full system or parallel scanner
if ($StartAll) {
    Write-Host "[3/3] Demarrage de l'orchestrateur complet (Backend + Scanner + Sidecar + Watcher)..." -ForegroundColor Cyan
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$devPath\start_all.ps1" -Workers $Workers -Order $Order
} else {
    Write-Host "[3/3] Lancement du scan batch parallele..." -ForegroundColor Cyan
    & uv run python -m reposcroller.main scan --workers $Workers --order $Order
}
