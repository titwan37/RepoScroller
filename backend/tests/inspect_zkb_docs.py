import sqlite3

conn = sqlite3.connect('backend/data/reposcroller_ledger.db')
cur = conn.cursor()

cur.execute("""
    SELECT c.sha256_hash, d.canonical_filename, c.chunk_text
    FROM document_chunks c
    JOIN document_ledger d ON c.sha256_hash = d.sha256_hash
    WHERE LOWER(c.chunk_text) LIKE '%zuger%kantonal%'
       OR LOWER(c.chunk_text) LIKE '%zgkb%'
       OR LOWER(c.chunk_text) LIKE '%kantonalbank zug%'
    LIMIT 5
""")

rows = cur.fetchall()
print(f"Matched {len(rows)} chunks:")
for r in rows:
    print("=" * 60)
    print("File:", r[1])
    print("Chunk Text sample:\n", r[2][:600])
