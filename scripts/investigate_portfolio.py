import sqlite3
from backend.ledger.db import get_db_connection

conn = get_db_connection()
cur = conn.cursor()

print("=== 1. TOTAL FILE LOCATIONS WITH PORTFOLIO IN PATH ===")
cur.execute("""
    SELECT COUNT(DISTINCT fl.sha256_hash), COUNT(*)
    FROM file_locations fl
    WHERE LOWER(fl.relative_path) LIKE '%portfolio%' 
       OR LOWER(fl.absolute_path) LIKE '%portfolio%';
""")
print("Distinct sha / Total locations:", cur.fetchone())

print("\n=== 2. BREAKDOWN OF DOC_TYPES FOR FILES IN PORTFOLIO PATHS ===")
cur.execute("""
    SELECT dl.doc_type, COUNT(DISTINCT dl.sha256_hash) as cnt
    FROM file_locations fl
    JOIN document_ledger dl ON fl.sha256_hash = dl.sha256_hash
    WHERE LOWER(fl.relative_path) LIKE '%portfolio%' 
       OR LOWER(fl.absolute_path) LIKE '%portfolio%'
    GROUP BY dl.doc_type
    ORDER BY cnt DESC;
""")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")

print("\n=== 3. SAMPLES OF FILES IN PORTFOLIO PATHS ===")
cur.execute("""
    SELECT dl.canonical_filename, dl.doc_type, fl.relative_path
    FROM file_locations fl
    JOIN document_ledger dl ON fl.sha256_hash = dl.sha256_hash
    WHERE LOWER(fl.relative_path) LIKE '%portfolio%' 
       OR LOWER(fl.absolute_path) LIKE '%portfolio%'
    LIMIT 20;
""")
for r in cur.fetchall():
    print(f"  [{r['doc_type']}] {r['canonical_filename']} (path: {r['relative_path']})")

print("\n=== 4. TOTAL DOCS IN DOCUMENT_LEDGER WHERE doc_type = 'career_portfolio' ===")
cur.execute("SELECT COUNT(*) FROM document_ledger WHERE doc_type = 'career_portfolio';")
print("career_portfolio count in ledger:", cur.fetchone()[0])

print("\n=== 5. KNOWLEDGE NODES MATCHING PORTFOLIO ===")
cur.execute("""
    SELECT node_id, node_type, name 
    FROM knowledge_nodes 
    WHERE LOWER(name) LIKE '%portfolio%' OR LOWER(node_id) LIKE '%portfolio%';
""")
for r in cur.fetchall():
    print(f"  {r['node_id']} ({r['node_type']}): {r['name']}")

print("\n=== 6. LINKS IN document_entity_links FOR PORTFOLIO NODES ===")
cur.execute("""
    SELECT node_id, role, COUNT(sha256_hash) 
    FROM document_entity_links 
    WHERE LOWER(node_id) LIKE '%portfolio%'
    GROUP BY node_id, role;
""")
for r in cur.fetchall():
    print(f"  {r[0]} (role: {r[1]}): {r[2]} links")

print("\n=== 7. CHECK WHAT NODE THE USER IS CLICKING IN 3D GRAPH ===")
cur.execute("""
    SELECT node_id, node_type, name, properties_json 
    FROM knowledge_nodes 
    WHERE node_id LIKE '%career_portfolio%' OR name LIKE '%Career Portfolio%';
""")
for r in cur.fetchall():
    print(f"  {r['node_id']} | {r['node_type']} | {r['name']} | {r['properties_json']}")
