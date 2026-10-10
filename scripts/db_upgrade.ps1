.venv\Scripts\python -c "from backend.ledger.db import init_db; init_db(); print('Database schema successfully migrated.')"
# Backfill reception_date, due_date, and actionable obligations:
.venv\Scripts\python -m backend.main backfill-obligations

# Re-link entity and banking relationships (instant graph edges):
.venv\Scripts\python -m backend.main reindex-banking
