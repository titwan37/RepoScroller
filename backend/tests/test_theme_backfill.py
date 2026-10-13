import sqlite3
from backend.ledger.db import get_db_connection
from backend.ledger.repository import DocumentRepository
from backend.ledger.graph_store import PropertyGraphStore

conn = get_db_connection()
repo = DocumentRepository(conn=conn)
store = PropertyGraphStore(repository=repo)

print("Running backfill_theme_links() ...")
res = store.backfill_theme_links(batch_size=500)
print("Backfill result:")
for k, v in res.items():
    print(f"  {k}: {v}")

cur = conn.cursor()
print("\n=== UPDATED THEME DISTRIBUTION IN GRAPH ===")
cur.execute("""
    SELECT kn.node_id, kn.name, COUNT(del.sha256_hash) as doc_count
    FROM knowledge_nodes kn
    JOIN document_entity_links del ON kn.node_id = del.node_id
    WHERE kn.node_type = 'theme'
    GROUP BY kn.node_id
    ORDER BY doc_count DESC
""")
for r in cur.fetchall():
    print(f"  {r[1]} ({r[0]}): {r[2]} docs")
