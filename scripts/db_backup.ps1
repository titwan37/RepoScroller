# 1. Checkpoint WAL and copy database to a dated backup
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item "c:\Dev\RepoScroller\backend\data\reposcroller_ledger.db" "c:\Dev\RepoScroller\backend\data\reposcroller_ledger_$timestamp.db.bak"

# If WAL and SHM files exist, copy them as well:
if (Test-Path "c:\Dev\RepoScroller\backend\data\reposcroller_ledger.db-wal") {
    Copy-Item "c:\Dev\RepoScroller\backend\data\reposcroller_ledger.db-wal" "c:\Dev\RepoScroller\backend\data\reposcroller_ledger_$timestamp.db-wal.bak"
}
