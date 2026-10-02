import sqlite3
from backend.ledger.db import resolve_ledger_db_path

db_path = resolve_ledger_db_path()
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
print("Tables:", [r["name"] for r in cur.fetchall()])

# Inspect New York documents & chunks
cur.execute("""
    SELECT dl.sha256_hash, dl.canonical_filename, dl.doc_type, dl.doc_date, dl.text_snippet
    FROM document_entity_links del
    JOIN document_ledger dl ON del.sha256_hash = dl.sha256_hash
    WHERE LOWER(del.node_id) = 'location_new_york'
    LIMIT 10;
""")
print("\n=== SAMPLE DOCUMENTS LINKED TO 'location_new_york' ===")
for r in cur.fetchall():
    print(f"\nFile: {r['canonical_filename']}")
    print(f"Type: {r['doc_type']} | Date: {r['doc_date']}")
    print(f"Snippet: {r['text_snippet']}")
    
    # Check chunks for this document
    cur.execute("SELECT chunk_text FROM document_chunks WHERE sha256_hash = ? AND (chunk_text LIKE '%New York%' OR chunk_text LIKE '%new york%' OR chunk_text LIKE '%NY%') LIMIT 2;", (r['sha256_hash'],))
    chunks = cur.fetchall()
    for c in chunks:
        txt = c["chunk_text"]
        idx = txt.lower().find("new york")
        if idx != -1:
            print(f"  Chunk excerpt: ...{txt[max(0, idx-60):min(len(txt), idx+80)]}...")
        else:
            print(f"  Chunk excerpt: {txt[:120]}...")

# Check location nodes for Zug
print("\n=== LOCATION NODES FOR ZUG ===")
cur.execute("SELECT node_id, name, properties_json FROM knowledge_nodes WHERE node_type = 'location' AND (LOWER(name) LIKE '%zug%' OR LOWER(node_id) LIKE '%zug%');")
for r in cur.fetchall():
    cur.execute("SELECT COUNT(*) FROM document_entity_links WHERE node_id = ?", (r["node_id"],))
    cnt = cur.fetchone()[0]
    print(f"ID: {r['node_id']} | Name: {r['name']} | Doc count: {cnt} | Props: {r['properties_json']}")

# Check how many documents mention 'Zug' in document_chunks
for word in ['Zug', '6300', 'Baar', 'Steinhausen', 'Ottenbach', 'Zuger']:
    cur.execute(f"SELECT COUNT(DISTINCT sha256_hash) FROM document_chunks WHERE chunk_text LIKE '%{word}%';")
    cnt = cur.fetchone()[0]
    print(f"Documents with chunk mentioning '{word}': {cnt}")
