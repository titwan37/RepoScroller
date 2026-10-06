import sqlite3

conn = sqlite3.connect('backend/data/reposcroller_showcase.db')
cur = conn.cursor()

before = cur.execute("SELECT COUNT(1) FROM document_entity_links WHERE node_id = 'location_steinhausen'").fetchone()[0]
print(f"Showcase before: location_steinhausen links={before}")

cur.execute("""
    INSERT OR IGNORE INTO document_entity_links (sha256_hash, node_id, role, confidence)
    SELECT dgl.sha256_hash, 'location_steinhausen', 'LOCATED_IN', COALESCE(dgl.confidence, 1.0)
    FROM document_geo_links dgl
    WHERE dgl.geo_id = 'CH-ZG-6312'
      AND EXISTS (SELECT 1 FROM knowledge_nodes n WHERE n.node_id = 'location_steinhausen')
      AND EXISTS (SELECT 1 FROM document_ledger dl WHERE dl.sha256_hash = dgl.sha256_hash);
""")
conn.commit()

after = cur.execute("SELECT COUNT(1) FROM document_entity_links WHERE node_id = 'location_steinhausen'").fetchone()[0]
print(f"Showcase after: location_steinhausen links={after} (added {after - before})")

conn.close()
