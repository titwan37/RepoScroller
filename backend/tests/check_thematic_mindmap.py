import sqlite3
from collections import Counter
from backend.ledger.db import get_db_connection

conn = get_db_connection()
cur = conn.cursor()

print("=== THEME NODES IN KNOWLEDGE GRAPH ===")
cur.execute("SELECT node_id, name, properties_json FROM knowledge_nodes WHERE node_type = 'theme'")
theme_nodes = cur.fetchall()
for tn in theme_nodes:
    print(f"  {tn['node_id']}: {tn['name']}")

print(f"\nTotal theme nodes: {len(theme_nodes)}")

print("\n=== DOCUMENT LINKS TO THEMES (document_entity_links) ===")
cur.execute("""
    SELECT kn.node_id, kn.name, COUNT(del.sha256_hash) as doc_count
    FROM knowledge_nodes kn
    JOIN document_entity_links del ON kn.node_id = del.node_id
    WHERE kn.node_type = 'theme'
    GROUP BY kn.node_id
    ORDER BY doc_count DESC
""")
theme_links = cur.fetchall()
for tl in theme_links:
    print(f"  {tl['name']} ({tl['node_id']}): {tl['doc_count']} docs linked")

print("\n=== THEME EDGES (knowledge_edges) ===")
cur.execute("""
    SELECT relation_type, COUNT(*) as cnt
    FROM knowledge_edges
    WHERE relation_type = 'CATEGORIZED_AS'
    GROUP BY relation_type
""")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]} edges")

print("\n=== MISMATCH CHECK: DOCUMENT DOC_TYPE VS LINKED THEME ===")
cur.execute("""
    SELECT dl.doc_type, kn.node_id, kn.name, COUNT(*) as cnt
    FROM document_ledger dl
    JOIN document_entity_links del ON dl.sha256_hash = del.sha256_hash
    JOIN knowledge_nodes kn ON del.node_id = kn.node_id
    WHERE kn.node_type = 'theme'
    GROUP BY dl.doc_type, kn.node_id
    ORDER BY cnt DESC
    LIMIT 25
""")
mismatches = cur.fetchall()
for m in mismatches:
    print(f"  doc_type='{m['doc_type']}' -> linked theme: '{m['name']}' ({m['node_id']}): {m['cnt']} docs")
