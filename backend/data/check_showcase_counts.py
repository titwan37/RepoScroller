import sqlite3
from pathlib import Path

showcase = Path("backend/data/reposcroller_showcase.db")
conn = sqlite3.connect(showcase)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("=== SHOWCASE DB ZUG NODES ===")
cur.execute("SELECT node_id, node_type, name FROM knowledge_nodes WHERE LOWER(name) LIKE '%zug%' OR LOWER(node_id) LIKE '%zug%';")
for r in cur.fetchall():
    cur.execute("SELECT COUNT(*) FROM document_entity_links WHERE node_id = ?", (r["node_id"],))
    cnt = cur.fetchone()[0]
    print(f"[{r['node_type']}] ID: {r['node_id']} | Name: {r['name']} | Doc count: {cnt}")

print("\n=== SHOWCASE DB NEW YORK NODES ===")
cur.execute("SELECT node_id, node_type, name FROM knowledge_nodes WHERE LOWER(name) LIKE '%york%' OR LOWER(node_id) LIKE '%york%';")
for r in cur.fetchall():
    cur.execute("SELECT COUNT(*) FROM document_entity_links WHERE node_id = ?", (r["node_id"],))
    cnt = cur.fetchone()[0]
    print(f"[{r['node_type']}] ID: {r['node_id']} | Name: {r['name']} | Doc count: {cnt}")
