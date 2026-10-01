powershell -Command "$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'; $bakPath = \"C:\Dev\RepoScroller\reposcroller_ledger_${timestamp}.db.bak\"; if (Test-Path 'C:\Dev\RepoScroller\reposcroller_ledger.db') { Copy-Item 'C:\Dev\RepoScroller\reposcroller_ledger.db' $bakPath; Copy-Item 'C:\Dev\RepoScroller\reposcroller_ledger.db' 'C:\Dev\RepoScroller\reposcroller_ledger.db.bak'; Get-Item $bakPath | Select-Object Name, Length, LastWriteTime }"

uv run python -c "import shutil, datetime, os; ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S'); bak_name = f'reposcroller_ledger_{ts}.db.bak'; shutil.copy2('reposcroller_ledger.db', bak_name); shutil.copy2('reposcroller_ledger.db', 'reposcroller_ledger.db.bak'); sz = os.path.getsize(bak_name); print(f'Backup created: {bak_name} ({sz / (1024*1024):.2f} MB)')"

uv run python -m reposcroller.main reset -y --no-backup

uv run python -c "from reposcroller.ledger.db import get_db_connection; conn = get_db_connection(); print('Doc count:', conn.execute('SELECT COUNT(*) FROM document_ledger').fetchone()[0])"

uv run python -c "from reposcroller.ledger.db import get_db_connection; conn = get_db_connection(); print('Document count in clean DB:', conn.execute('SELECT COUNT(*) FROM document_ledger').fetchone()[0])"