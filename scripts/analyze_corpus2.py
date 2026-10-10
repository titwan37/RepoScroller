import sqlite3
from collections import Counter
from backend.ledger.db import get_db_connection

conn = get_db_connection()
cur = conn.cursor()

print("=== 1. GLOBAL TAXONOMY TABLE ===")
cur.execute("SELECT category_id, parent_id, name_en, document_count FROM global_taxonomy")
for row in cur.fetchall():
    print(f"  {row['category_id']} (parent: {row['parent_id']}): {row['name_en']} [{row['document_count']} docs]")

print("\n=== 2. TAXONOMY VERSIONS TABLE ===")
cur.execute("SELECT version, name, status, applied_at FROM taxonomy_versions")
for row in cur.fetchall():
    print(f"  {row['version']} ({row['status']}): {row['name']} at {row['applied_at']}")

print("\n=== 3. STORAGE ROOTS (file_locations) ===")
cur.execute("SELECT storage_root, COUNT(*) as cnt FROM file_locations GROUP BY storage_root ORDER BY cnt DESC")
for row in cur.fetchall():
    print(f"  {row['storage_root']}: {row['cnt']}")

print("\n=== 4. TOP FOLDERS / PATHS (file_locations) ===")
cur.execute("SELECT relative_path FROM file_locations LIMIT 1000")
paths = [r[0] for r in cur.fetchall()]
folder_counter = Counter()
for p in paths:
    parts = p.replace('\\', '/').split('/')
    if len(parts) > 1:
        folder_counter[parts[0]] += 1
for folder, cnt in folder_counter.most_common(20):
    print(f"  Top root folder: {folder} ({cnt})")

print("\n=== 5. KNOWLEDGE NODES BY TYPE ===")
cur.execute("SELECT node_type, COUNT(*) as cnt FROM knowledge_nodes GROUP BY node_type ORDER BY cnt DESC")
for row in cur.fetchall():
    print(f"  {row['node_type']}: {row['cnt']}")

print("\n=== 6. TOP ORGANIZATIONS IN GRAPH ===")
cur.execute("""
    SELECT kn.name, COUNT(del.sha256_hash) as doc_count
    FROM knowledge_nodes kn
    JOIN document_entity_links del ON kn.node_id = del.node_id
    WHERE kn.node_type = 'organization'
    GROUP BY kn.node_id
    ORDER BY doc_count DESC
    LIMIT 25
""")
for row in cur.fetchall():
    print(f"  Org: {row['name']} -> {row['doc_count']} docs")

print("\n=== 7. ACTION ITEMS BY TYPE ===")
cur.execute("SELECT action_type, status, COUNT(*) as cnt FROM action_items GROUP BY action_type, status ORDER BY cnt DESC")
for row in cur.fetchall():
    print(f"  {row['action_type']} ({row['status']}): {row['cnt']}")

print("\n=== 8. DOC_TYPE 'other' DEEP DIVE (Sample titles and patterns) ===")
cur.execute("SELECT canonical_filename, text_snippet FROM document_ledger WHERE doc_type = 'other' LIMIT 40")
for row in cur.fetchall():
    fn = row['canonical_filename']
    snip = (row['text_snippet'] or '')[:70].replace('\n', ' ')
    print(f"  FILE: {fn} | SNIP: {snip}")
