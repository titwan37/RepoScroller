import sqlite3
from backend.ledger.repository import DocumentRepository
from backend.ledger.graph_store import PropertyGraphStore

print("=== Backfilling and verifying reposcroller_ledger.db ===")
repo1 = DocumentRepository(db_path="backend/data/reposcroller_ledger.db")
gs1 = PropertyGraphStore(repository=repo1)
res1 = gs1.backfill_geo_entity_links()
print("Backfill result ledger:", res1)

cur1 = repo1.conn.cursor()
cur1.execute("""
    SELECT n.node_id, n.name, COUNT(DISTINCT l.sha256_hash) AS doc_count, MAX(dl.doc_date) AS latest_date
    FROM knowledge_nodes n
    JOIN document_entity_links l ON n.node_id = l.node_id
    JOIN document_ledger dl ON l.sha256_hash = dl.sha256_hash
    WHERE n.node_id IN ('location_ch_zg_6312', 'location_steinhausen')
    GROUP BY n.node_id
""")
for r in cur1.fetchall():
    print("Ledger node:", r)

print("\n=== Backfilling and verifying reposcroller_showcase.db ===")
repo2 = DocumentRepository(db_path="backend/data/reposcroller_showcase.db")
gs2 = PropertyGraphStore(repository=repo2)
res2 = gs2.backfill_geo_entity_links()
print("Backfill result showcase:", res2)

cur2 = repo2.conn.cursor()
cur2.execute("""
    SELECT n.node_id, n.name, COUNT(DISTINCT l.sha256_hash) AS doc_count, MAX(dl.doc_date) AS latest_date
    FROM knowledge_nodes n
    JOIN document_entity_links l ON n.node_id = l.node_id
    JOIN document_ledger dl ON l.sha256_hash = dl.sha256_hash
    WHERE n.node_id IN ('location_ch_zg_6312', 'location_steinhausen')
    GROUP BY n.node_id
""")
for r in cur2.fetchall():
    print("Showcase node:", r)

# Verify expand_entity_neighborhood for Steinhausen
print("\n=== Testing expand_entity_neighborhood('location_ch_zg_6312') ===")
nh1 = gs1.expand_entity_neighborhood('location_ch_zg_6312')
print("Associated docs count in neighborhood:", len(nh1['associated_documents']))
if nh1['associated_documents']:
    print("Sample associated docs:")
    for d in nh1['associated_documents'][:5]:
        print("  -", d['canonical_filename'], f"({d['doc_date']})")
