import sys
sys.path.insert(0, r"c:\Dev\RepoScroller")
import sqlite3
import json
from backend.config import settings

conn = sqlite3.connect(settings.DB_PATH)
c = conn.cursor()

c.execute("SELECT status, count(*) FROM kb_processing_queue GROUP BY status")
print("kb_processing_queue counts:", c.fetchall())

# Let's check status of the .xml files in kb_processing_queue
c.execute("""
    SELECT q.status, count(*) 
    FROM kb_processing_queue q
    JOIN document_ledger dl ON q.sha256_hash = dl.sha256_hash
    WHERE dl.canonical_filename LIKE '%.xml'
    GROUP BY q.status
""")
print("XML files status in kb_processing_queue:", c.fetchall())

# Sample chunk from XML
c.execute("""
    SELECT c.chunk_id, c.sha256_hash, dl.canonical_filename, c.embedding_json
    FROM document_chunks c
    JOIN document_ledger dl ON c.sha256_hash = dl.sha256_hash
    WHERE dl.canonical_filename LIKE '%.xml'
    LIMIT 2
""")
for r in c.fetchall():
    emb = json.loads(r[3]) if r[3] else None
    non_zeros = sum(1 for x in emb if x != 0.0) if emb else 0
    print(f"File: {r[2]}, Chunk: {r[0]}, emb len: {len(emb) if emb else 0}, non_zeros: {non_zeros}")
