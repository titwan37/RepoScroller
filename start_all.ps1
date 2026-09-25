# RepoScroller - Orchestrateur Multi-Consoles (PowerShell)
# Lance les services necessaires (Backend FastAPI, Scanner Parallele, Watcher, Ollama)
# Mode Windows Terminal multi-onglets ou consoles separees (modele AuraBily)

param (
    [switch]$UseWindowsTerminal = $true,
    [switch]$OpenBrowser = $true,
    [switch]$StartScanner = $true,
    [switch]$StartWatcher = $true,
    [switch]$StartSidecar = $true,
    [switch]$ForceOllamaTab = $false,
    [int]$Port = 8090,
    [int]$Workers = 6,
    [string]$Order = "antichronological"
)

$devPath = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($devPath)) {
    $devPath = "C:\Dev\RepoScroller"
}

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "   RepoScroller Sovereign Studio - Orchestrateur de Services" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " Repertoire projet : $devPath" -ForegroundColor Gray
Write-Host " Mode execution    : $(if ($UseWindowsTerminal) { 'Windows Terminal (Multi-Onglets)' } else { 'Consoles Separees' })" -ForegroundColor Gray
Write-Host " Pool scanner      : $Workers threads en parallele ($Order)" -ForegroundColor Gray
Write-Host " KB Sidecar        : $(if ($StartSidecar) { 'Actif (snowflake-arctic-embed + Neo4j/SQLite Graph)' } else { 'Desactive' })" -ForegroundColor Gray
Write-Host ""

# 1. Verification de l'environnement uv Python
if (Get-Command uv.exe -ErrorAction SilentlyContinue) {
    Write-Host "[DETECTE] Environnement uv Python pret." -ForegroundColor Green
}
else {
    Write-Host "[ATTENTION] uv n a pas ete detecte dans le PATH." -ForegroundColor Yellow
}

# 2. Sondage des 6 referentiels de stockage (SMB et Google Drive)
Write-Host ""
Write-Host "Sondage des 6 referentiels de stockage (SMB et Google Drive) :" -ForegroundColor Cyan
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
        Write-Host "  [CONNECTE]  [OK] $root" -ForegroundColor Green
        $onlineCount++
    }
    else {
        Write-Host "  [HORS LIGNE] [!!] $root (non monte ou inaccessible)" -ForegroundColor DarkYellow
    }
}
Write-Host "  -> $onlineCount sur $($roots.Count) referentiels en ligne." -ForegroundColor Gray
Write-Host ""

# 3. Verification d Ollama (Service / Processus)
$hasOllamaInstalled = (Get-Command ollama.exe -ErrorAction SilentlyContinue) -ne $null
$isOllamaListening = $false

if ($hasOllamaInstalled) {
    $listeningCheck = netstat -ano | findstr :11434 | findstr LISTENING
    if ($listeningCheck) {
        $isOllamaListening = $true
        Write-Host "[DETECTE] Serveur Ollama deja actif et en ecoute (http://127.0.0.1:11434)." -ForegroundColor Green
    }
    else {
        Write-Host "[DETECTE] Ollama installe mais non actif. Il sera demarre dans un onglet." -ForegroundColor Yellow
    }
}
else {
    Write-Host "[INFO] Ollama non present sur cette machine (fallback RAG distant/heuristique actif)." -ForegroundColor DarkGray
}

$needStartOllama = $hasOllamaInstalled -and (-not $isOllamaListening -or $ForceOllamaTab)

Write-Host ""

# 4. Lancement Windows Terminal (Multi-Onglets) ou Consoles separees
if ($UseWindowsTerminal -and (Get-Command wt.exe -ErrorAction SilentlyContinue)) {
    Write-Host "[Mode Windows Terminal Multi-Onglets]" -ForegroundColor Green

    $wtArgs = @("-w", "0", "new-tab", "--title", "RepoScroller Backend", "-d", "$devPath", "cmd.exe", "/k", "start_backend.bat")

    if ($StartScanner) {
        $wtArgs += @(";", "new-tab", "--title", "Parallel Scanner (x$Workers)", "-d", "$devPath", "cmd.exe", "/k", "start_scanner.bat")
    }

    if ($StartWatcher) {
        $wtArgs += @(";", "new-tab", "--title", "Watcher Daemon", "-d", "$devPath", "cmd.exe", "/k", "start_watcher.bat")
    }

    if ($StartSidecar) {
        $wtArgs += @(";", "new-tab", "--title", "KB Sidecar (GraphRAG)", "-d", "$devPath", "cmd.exe", "/k", "start_sidecar.bat")
    }

    if ($needStartOllama) {
        $wtArgs += @(";", "new-tab", "--title", "Ollama Server", "-d", "$devPath", "cmd.exe", "/k", "start_ollama.bat")
    }

    & wt.exe @wtArgs
}
else {
    Write-Host "[Mode Consoles Separees]" -ForegroundColor Green

    # 1. Console Backend FastAPI
    Write-Host "[1/4] Lancement du Backend RepoScroller (FastAPI :$Port)..." -ForegroundColor Cyan
    Start-Process -FilePath "cmd.exe" -WorkingDirectory $devPath -ArgumentList "/k", "start_backend.bat"
    Start-Sleep -Seconds 2

    # 2. Console Scanner Parallele
    if ($StartScanner) {
        Write-Host "[2/4] Lancement du Scanner Parallele ($Workers threads)..." -ForegroundColor Cyan
        Start-Process -FilePath "cmd.exe" -WorkingDirectory $devPath -ArgumentList "/k", "start_scanner.bat"
        Start-Sleep -Seconds 1
    }

    # 3. Console Watcher Daemon
    if ($StartWatcher) {
        Write-Host "[3/4] Lancement du Watcher Daemon continu..." -ForegroundColor Cyan
        Start-Process -FilePath "cmd.exe" -WorkingDirectory $devPath -ArgumentList "/k", "start_watcher.bat"
        Start-Sleep -Seconds 1
    }

    # 4. Console Knowledge Base Sidecar (Vectors & Graph)
    if ($StartSidecar) {
        Write-Host "[4/4] Lancement du Knowledge Base Sidecar (Vectors & Graph)..." -ForegroundColor Cyan
        Start-Process -FilePath "cmd.exe" -WorkingDirectory $devPath -ArgumentList "/k", "start_sidecar.bat"
        Start-Sleep -Seconds 1
    }

    # 5. Console Ollama (si necessaire)
    if ($needStartOllama) {
        Write-Host "[+] Lancement du Serveur Ollama..." -ForegroundColor DarkCyan
        Start-Process -FilePath "cmd.exe" -WorkingDirectory $devPath -ArgumentList "/k", "start_ollama.bat"
    }
}

# 5. Ouverture automatique du navigateur
if ($OpenBrowser) {
    Start-Sleep -Seconds 2
    Write-Host "[Navigateur] Ouverture du Dashboard RepoScroller (http://127.0.0.1:$Port)..." -ForegroundColor Green
    Start-Process "http://127.0.0.1:$Port"
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Services RepoScroller initialises avec succes !" -ForegroundColor Cyan
Write-Host "   1. Dashboard Web & API         : http://127.0.0.1:$Port/" -ForegroundColor White
Write-Host "   2. Explorateur OpenAPI (docs)  : http://127.0.0.1:$Port/docs" -ForegroundColor Gray
Write-Host "   3. Knowledge Base Sidecar Stats: http://127.0.0.1:$Port/api/v1/sidecar/stats" -ForegroundColor Gray
Write-Host "   4. Diagnostics & Telemetrie    : http://127.0.0.1:$Port/api/v1/diagnostics/health" -ForegroundColor Gray
Write-Host "   5. Console Diagnostic Flottante: Integree au Dashboard Web" -ForegroundColor Gray
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""