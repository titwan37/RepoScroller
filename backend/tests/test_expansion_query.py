import sqlite3
from backend.ledger.db import resolve_ledger_db_path

db_path = resolve_ledger_db_path()
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

loc_filter = "zurich"
cur.execute("SELECT node_id FROM knowledge_nodes WHERE node_type = 'location' AND (LOWER(name) LIKE ? OR LOWER(node_id) LIKE ?);", (f"%{loc_filter.lower()}%", f"%{loc_filter.lower()}%"))
loc_node_ids = {r["node_id"] for r in cur.fetchall()}
print("Matching location nodes:", loc_node_ids)

matching_node_ids = set(loc_node_ids)

if loc_node_ids:
    p_loc = ",".join("?" for _ in loc_node_ids)
    loc_list = list(loc_node_ids)
    
    # 1. Direct edge neighbors
    cur.execute(f"""
        SELECT DISTINCT CASE WHEN source_id IN ({p_loc}) THEN target_id ELSE source_id END AS neighbor_id
        FROM knowledge_edges
        WHERE source_id IN ({p_loc}) OR target_id IN ({p_loc})
        LIMIT 100;
    """, loc_list + loc_list + loc_list)
    direct_neighbors = {r["neighbor_id"] for r in cur.fetchall()}
    matching_node_ids.update(direct_neighbors)
    print("Direct edge neighbors found:", len(direct_neighbors))

    # 2. Co-occurring entities via shared documents
    cur.execute(f"""
        SELECT l2.node_id, COUNT(DISTINCT l1.sha256_hash) as shared_docs
        FROM document_entity_links l1
        JOIN document_entity_links l2 ON l1.sha256_hash = l2.sha256_hash
        WHERE l1.node_id IN ({p_loc}) AND l2.node_id NOT IN ({p_loc})
        GROUP BY l2.node_id
        ORDER BY shared_docs DESC
        LIMIT 150;
    """, loc_list + loc_list)
    co_entities = {r["node_id"] for r in cur.fetchall()}
    matching_node_ids.update(co_entities)
    print("Co-occurring entities found:", len(co_entities))

print("Total matching nodes in expanded subgraph:", len(matching_node_ids))

p_all = ",".join("?" for _ in matching_node_ids)
cur.execute(f"SELECT node_type, COUNT(*) as cnt FROM knowledge_nodes WHERE node_id IN ({p_all}) GROUP BY node_type;", list(matching_node_ids))
print("Entity breakdown:", [dict(r) for r in cur.fetchall()])
