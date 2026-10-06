# In reposcroller directory
sqlite3 reposcroller.db "PRAGMA journal_mode=WAL;"
sqlite3 reposcroller.db "PRAGMA busy_timeout=30000;"
sqlite3 reposcroller.db "PRAGMA wal_checkpoint(TRUNCATE);"