import sqlite3

conn = sqlite3.connect('backend/data/reposcroller_ledger.db')
cur = conn.cursor()

# Get properties of location_ch_zg_6312
cur.execute("SELECT node_id, node_type, name, properties_json FROM knowledge_nodes WHERE node_id IN ('location_ch_zg_6312', 'location_steinhausen')")
for r in cur.fetchall():
    print("Node:", r[0], r[1], r[2], r[3])

# Edges for location_ch_zg_6312
cur.execute("SELECT source_id, target_id, relation_type, weight, properties_json FROM knowledge_edges WHERE source_id = 'location_ch_zg_6312' OR target_id = 'location_ch_zg_6312'")
edges = cur.fetchall()
print(f"\nEdges count for location_ch_zg_6312: {len(edges)}")
for e in edges[:10]:
    print(" ", e)

# Edges for location_steinhausen
cur.execute("SELECT source_id, target_id, relation_type, weight FROM knowledge_edges WHERE source_id = 'location_steinhausen' OR target_id = 'location_steinhausen' LIMIT 10")
edges_st = cur.fetchall()
print(f"\nEdges count for location_steinhausen: {len(cur.execute('SELECT COUNT(*) FROM knowledge_edges WHERE source_id = \"location_steinhausen\" OR target_id = \"location_steinhausen\"').fetchall())}")
for e in edges_st:
    print(" ", e)

# What are the 2 neighborhood connections the user saw:
# "Kanton Zug PART_OF_CANTON"
# "WWZ Energie AG HEADQUARTERED_IN"
print("\nCheck if any edges connect to 'Kanton Zug' or 'WWZ Energie AG':")
cur.execute("""
    SELECT e.source_id, e.target_id, e.relation_type, n1.name, n2.name
    FROM knowledge_edges e
    JOIN knowledge_nodes n1 ON e.source_id = n1.node_id
    JOIN knowledge_nodes n2 ON e.target_id = n2.node_id
    WHERE (e.source_id LIKE '%steinhausen%' OR e.target_id LIKE '%steinhausen%')
""")
for r in cur.fetchall()[:20]:
    print("  ", r)

conn.close()
