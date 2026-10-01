# ==============================================================================
# RepoScroller Project Restructuring Migration Script
# ==============================================================================
# Usage:
#   .\migrate_structure.ps1 -WhatIf    # Preview changes without moving files
#   .\migrate_structure.ps1            # Perform the actual migration
# ==============================================================================

[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ProjectRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { 
    $ProjectRoot = (Get-Location).Path 
}

Write-Host "`n[1/6] Validating Project Root: $ProjectRoot" -ForegroundColor Cyan
if (-not (Test-Path "$ProjectRoot\pyproject.toml") -and -not (Test-Path "$ProjectRoot\reposcroller")) {
    Write-Error "Execution aborted: Script must be executed inside 'C:\Dev\RepoScroller'."
    exit 1
}

# ------------------------------------------------------------------------------
# 1. Directory Scaffolding Creation
# ------------------------------------------------------------------------------
Write-Host "`n[2/6] Scaffolding Target Directory Structure..." -ForegroundColor Cyan

$TargetDirs = @(
    "backend",
    "backend\data",
    "frontend",
    "frontend\public",
    "frontend\src",
    "frontend\src\app",
    "frontend\src\app\components",
    "frontend\src\app\services",
    "frontend\src\app\models",
    "scripts",
    "docs"
)

foreach ($dir in $TargetDirs) {
    $fullPath = "$ProjectRoot\$dir"
    if (-not (Test-Path $fullPath)) {
        if ($PSCmdlet.ShouldProcess($fullPath, "Create directory")) {
            New-Item -ItemType Directory -Path $fullPath -Force | Out-Null
            Write-Host "  [+] Created: $dir" -ForegroundColor Green
        }
    }
    else {
        Write-Host "  [=] Exists:  $dir" -ForegroundColor DarkGray
    }
}

# ------------------------------------------------------------------------------
# 2. Migrate Backend Core Packages & Configuration
# ------------------------------------------------------------------------------
Write-Host "`n[3/6] Migrating Backend Core Packages & Taxonomy..." -ForegroundColor Cyan

$BackendItemsToMove = @("reposcroller", "taxonomy", "tests")

foreach ($item in $BackendItemsToMove) {
    $source = "$ProjectRoot\$item"
    $dest = "$ProjectRoot\backend\$item"

    if (Test-Path $source) {
        if ($PSCmdlet.ShouldProcess($source, "Move to $dest")) {
            Move-Item -Path $source -Destination $dest -Force
            Write-Host "  [->] Moved: $item -> backend\$item" -ForegroundColor Green
        }
    }
}

$BackendConfigFiles = @("requirements.txt", "uv.lock")
foreach ($cfg in $BackendConfigFiles) {
    $source = "$ProjectRoot\$cfg"
    $dest = "$ProjectRoot\backend\$cfg"
    if (Test-Path $source) {
        if ($PSCmdlet.ShouldProcess($source, "Copy to backend\$cfg")) {
            Copy-Item -Path $source -Destination $dest -Force
            Write-Host "  [CP] Synced: $cfg -> backend\$cfg" -ForegroundColor Green
        }
    }
}

# ------------------------------------------------------------------------------
# 3. Migrate SQLite Ledger & Memory Data (ALCOA+ Isolation)
# ------------------------------------------------------------------------------
Write-Host "`n[4/6] Isolating Runtime Databases & Caches into backend\data..." -ForegroundColor Cyan

$DataPatterns = @("*.db", "*.db-wal", "*.db-shm", "*.db.bak", "*.sqlite")

foreach ($pattern in $DataPatterns) {
    Get-ChildItem -Path $ProjectRoot -Filter $pattern -File | ForEach-Object {
        $dest = "$ProjectRoot\backend\data\$($_.Name)"
        if ($PSCmdlet.ShouldProcess($_.FullName, "Move to $dest")) {
            Move-Item -Path $_.FullName -Destination $dest -Force
            Write-Host "  [->] Database isolated: $($_.Name) -> backend\data\" -ForegroundColor Yellow
        }
    }
}

$mbData = "$ProjectRoot\memoryblast_data"
if (Test-Path $mbData) {
    $mbDest = "$ProjectRoot\backend\data\memoryblast_data"
    if ($PSCmdlet.ShouldProcess($mbData, "Move to $mbDest")) {
        Move-Item -Path $mbData -Destination $mbDest -Force
        Write-Host "  [->] Cache moved: memoryblast_data -> backend\data\memoryblast_data" -ForegroundColor Yellow
    }
}

# ------------------------------------------------------------------------------
# 4. Migrate Scripts to /scripts Directory
# ------------------------------------------------------------------------------
Write-Host "`n[5/6] Moving Dev & Automation Scripts to /scripts..." -ForegroundColor Cyan

$ScriptPatterns = @(
    "start_*.bat", "start_*.ps1",
    "stop_*.bat", "stop_*.ps1",
    "setup_*.bat", "setup_*.ps1",
    "reset_*.bat", "reset_*.ps1",
    "setup.bat", "backup.ps1",
    "createDockerImage", "pushtoGit.bat"
)

foreach ($pattern in $ScriptPatterns) {
    Get-ChildItem -Path $ProjectRoot -Filter $pattern -File | ForEach-Object {
        if ($_.Name -ne "migrate_structure.ps1") {
            $dest = "$ProjectRoot\scripts\$($_.Name)"
            if ($PSCmdlet.ShouldProcess($_.FullName, "Move to $dest")) {
                Move-Item -Path $_.FullName -Destination $dest -Force
                Write-Host "  [->] Script relocated: $($_.Name) -> scripts\" -ForegroundColor Blue
            }
        }
    }
}

$DocFiles = @("candidate_instincts.md")
foreach ($doc in $DocFiles) {
    $source = "$ProjectRoot\$doc"
    $dest = "$ProjectRoot\docs\$doc"
    if (Test-Path $source) {
        if ($PSCmdlet.ShouldProcess($source, "Move to $dest")) {
            Move-Item -Path $source -Destination $dest -Force
            Write-Host "  [->] Document relocated: $doc -> docs\$doc" -ForegroundColor Blue
        }
    }
}

# ------------------------------------------------------------------------------
# 5. Update .gitignore for the New Structure
# ------------------------------------------------------------------------------
Write-Host "`n[6/6] Checking .gitignore configuration..." -ForegroundColor Cyan

$GitIgnorePath = "$ProjectRoot\.gitignore"
$RulesToAdd = @(
    "",
    "# --- RepoScroller Tier Separation ---",
    "backend/data/*.db",
    "backend/data/*.db-wal",
    "backend/data/*.db-shm",
    "backend/data/*.bak",
    "backend/data/memoryblast_data/",
    "backend/data/chroma_db/",
    "frontend/dist/",
    "frontend/node_modules/",
    ".pytest_cache/",
    "__pycache__/",
    "*.pyc"
)

if (Test-Path $GitIgnorePath) {
    $currentContent = Get-Content $GitIgnorePath -Raw
    $needsAppend = $false
    foreach ($rule in $RulesToAdd) {
        if ($rule -and -not $rule.StartsWith("#") -and -not $currentContent.Contains($rule)) {
            $needsAppend = $true
            break
        }
    }
    if ($needsAppend) {
        if ($PSCmdlet.ShouldProcess($GitIgnorePath, "Append directory isolation ignore rules")) {
            Add-Content -Path $GitIgnorePath -Value ($RulesToAdd -join "`n")
            Write-Host "  [OK] Updated .gitignore with backend/data and frontend exclusions." -ForegroundColor Green
        }
    }
    else {
        Write-Host "  [OK] .gitignore already contains isolation rules." -ForegroundColor DarkGray
    }
}

Write-Host "`nMigration complete. The project layout is successfully structured.`n" -ForegroundColor Green