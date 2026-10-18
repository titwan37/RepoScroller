import sys
sys.path.insert(0, r"c:\Dev\RepoScroller")
import sqlite3
import json
from backend.config import settings

conn = sqlite3.connect(settings.DB_PATH)
c = conn.cursor()

c.execute("SELECT status, count(*) FROM kb_processing_queue GROUP BY status")
print("Queue status:", c.fetchall())

c.execute("""
    SELECT dl.canonical_filename, q.status, q.enqueued_at 
    FROM kb_processing_queue q 
    JOIN document_ledger dl ON q.sha256_hash = dl.sha256_hash 
    WHERE q.status != 'completed'
""")
for r in c.fetchall():
    print("In progress:", r[0], r[1])

c.execute("""
    SELECT c.chunk_id, dl.canonical_filename, c.embedding_json
    FROM document_chunks c
    JOIN document_ledger dl ON c.sha256_hash = dl.sha256_hash
    WHERE dl.canonical_filename LIKE '%.xml' AND c.embedding_json IS NOT NULL
    LIMIT 3
""")
rows = c.fetchall()
if rows:
    for row in rows:
        emb = json.loads(row[2])
        non_zeros = sum(1 for x in emb if x != 0.0)
        print(f"XML chunk {row[0]} ({row[1]}): {non_zeros}/1024 non-zeros")
else:
    print("No embedded XML chunks found yet.")


import urllib.request, ssl, json
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
url = 'https://afastudio.ch/reposcroller/api/v1/documents/?limit=500'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
    data = json.loads(r.read().decode('utf-8'))
docs = data.get('documents', []) if isinstance(data, dict) else data
print('Total docs:', len(docs))
quotes_docs = [d for d in docs if \"'\" in d.get('canonical_filename', '')]
print('Docs with single quote in filename:', len(quotes_docs))
for d in quotes_docs:
    print('  SHA:', d.get('sha256_hash'), 'Filename:', d.get('canonical_filename'))


import urllib.request, ssl, json
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
url = 'https://afastudio.ch/reposcroller/api/v1/documents/ledger?limit=100'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
        data = json.loads(r.read().decode('utf-8'))
    docs = data.get('items', [])
    print('Total docs returned:', len(docs))
    for d in docs:
        name = d.get('canonical_filename', '')
        if \"'\" in name or '\"' in name:
            print('Doc with quote:', d.get('sha256_hash'), name)
except Exception as e:
    print('Error:', e)