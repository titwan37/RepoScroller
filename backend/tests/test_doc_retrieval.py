import sys
sys.path.insert(0, r"c:\Dev\RepoScroller")

from backend.ledger.db import get_db_connection

conn = get_db_connection()
cur = conn.cursor()

# Test the query that fetches doc_rows and connected entities for "court_order":
test_q = "court_order"
cur.execute("SELECT sha256_hash FROM document_ledger WHERE LOWER(doc_type) = ? OR LOWER(canonical_filename) LIKE ? LIMIT 10;", (test_q, f"%{test_q}%"))
shas = [r[0] for r in cur.fetchall()]
print(f"Matched {len(shas)} SHAs for court_order")

p_shas = ",".join("?" for _ in shas)
cur.execute(f"""
    SELECT dl.sha256_hash, dl.canonical_filename, dl.doc_type,
           (SELECT del.node_id FROM document_entity_links del WHERE del.sha256_hash = dl.sha256_hash AND del.node_id LIKE 'theme_%' LIMIT 1) AS theme_id,
           (SELECT COUNT(*) FROM document_entity_links del WHERE del.sha256_hash = dl.sha256_hash) AS degree
    FROM document_ledger dl
    WHERE dl.sha256_hash IN ({p_shas})
""", shas)
docs = cur.fetchall()
print(f"Retrieved {len(docs)} document rows:")
for d in docs[:5]:
    print(f"  - {d[1]} (type: {d[2]}, theme: {d[3]}, degree: {d[4]})")

cur.execute(f"""
    SELECT DISTINCT node_id FROM document_entity_links WHERE sha256_hash IN ({p_shas}) LIMIT 10;
""", shas)
linked_entities = [r[0] for r in cur.fetchall()]
print(f"Linked entities: {linked_entities[:5]}")
