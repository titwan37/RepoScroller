import sqlite3
from backend.tests.conftest import init_db
from pathlib import Path
import tempfile
d = Path(tempfile.mkdtemp())
f = d / 'test.db'
init_db(f)
from backend.ledger.db import get_db_connection
conn = get_db_connection(f)
from backend.ledger.repository import DocumentRepository
repo = DocumentRepository(conn=conn)
repo.upsert_document('sha_test_1', 'sim', 'fn', 'french_bail', 'final', 0.9, 0.9, 1, 'txt')
cur = conn.cursor()
cur.execute("SELECT sha256_hash, doc_type FROM document_ledger WHERE sha256_hash='sha_test_1'")
print([dict(r) for r in cur.fetchall()])
from backend.ai.taxonomy import TaxonomyManager
mgr = TaxonomyManager(db_conn=conn)
print("Before merge:", mgr.get_category('french_bail'))
reassigned = mgr.merge_categories('french_bail', 'unified_lease')
print("Merge rowcount:", reassigned)
