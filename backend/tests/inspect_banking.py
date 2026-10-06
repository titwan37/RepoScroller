import sqlite3

conn = sqlite3.connect('backend/data/reposcroller_ledger.db')
cur = conn.cursor()

print("--- PostFinance Nodes ---")
cur.execute("SELECT node_id, node_type, name, properties_json FROM knowledge_nodes WHERE LOWER(name) LIKE '%postfinance%' OR LOWER(node_id) LIKE '%postfinance%'")
for r in cur.fetchall():
    print(r)

print("\n--- Zug / Kantonalbank Nodes ---")
cur.execute("SELECT node_id, node_type, name, properties_json FROM knowledge_nodes WHERE LOWER(name) LIKE '%zug%' OR LOWER(name) LIKE '%kantonalbank%' OR LOWER(node_id) LIKE '%zug%'")
for r in cur.fetchall():
    print(r)

print("\n--- Document Ledger references to Zug / Kantonalbank / PostFinance ---")
cur.execute("SELECT sha256_hash, canonical_filename FROM document_ledger WHERE LOWER(canonical_filename) LIKE '%zug%' OR LOWER(canonical_filename) LIKE '%postfinance%' OR LOWER(text_snippet) LIKE '%zug%' OR LOWER(text_snippet) LIKE '%kantonalbank%' LIMIT 10")
for r in cur.fetchall():
    print(r)

print("\n--- Document Entity Links for PostFinance ---")
cur.execute("SELECT l.sha256_hash, l.node_id, l.role, d.canonical_filename FROM document_entity_links l JOIN document_ledger d ON l.sha256_hash = d.sha256_hash WHERE l.node_id LIKE '%postfinance%' LIMIT 5")
for r in cur.fetchall():
    print(r)
