import sqlite3

for db_path in ['backend/data/reposcroller_ledger.db', 'backend/data/reposcroller_showcase.db']:
    print(f"\n=== DB: {db_path} ===")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Find nodes where name is 'Steinhausen'
    cur.execute("SELECT node_id, node_type, name FROM knowledge_nodes WHERE LOWER(name) = 'steinhausen' OR LOWER(node_id) LIKE '%steinhausen%'")
    for r in cur.fetchall():
        nid, ntype, name = r
        # degree
        cur.execute("SELECT COUNT(*) FROM knowledge_edges WHERE source_id = ? OR target_id = ?", (nid, nid))
        deg = cur.fetchone()[0]
        # doc_count
        cur.execute("SELECT COUNT(DISTINCT sha256_hash) FROM document_entity_links WHERE node_id = ?", (nid,))
        dc = cur.fetchone()[0]
        # latest date
        cur.execute("""
            SELECT MAX(dl.doc_date) 
            FROM document_entity_links del 
            JOIN document_ledger dl ON del.sha256_hash = dl.sha256_hash 
            WHERE del.node_id = ?
        """, (nid,))
        ld = cur.fetchone()[0]
        if deg > 10 or dc > 0 or name == 'Steinhausen':
            print(f"Node [{nid}] ({ntype}): name='{name}', degree={deg}, doc_count={dc}, latest_doc_date={ld}")

    # Check which node in knowledge_edges has degree 8258!
    print("\nChecking any node in DB with degree near 8258:")
    cur.execute("""
        SELECT node_id, cnt FROM (
            SELECT source_id AS node_id, COUNT(*) as cnt FROM knowledge_edges GROUP BY source_id
            UNION ALL
            SELECT target_id AS node_id, COUNT(*) as cnt FROM knowledge_edges GROUP BY target_id
        ) GROUP BY node_id ORDER BY SUM(cnt) DESC LIMIT 10;
    """)
    for r in cur.fetchall():
        print(f"  High degree node: {r}")

    conn.close()
