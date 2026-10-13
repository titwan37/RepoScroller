import sys
sys.path.insert(0, r"c:\Dev\RepoScroller")

from backend.ledger.db import get_db_connection

conn = get_db_connection()
cur = conn.cursor()

cur.execute("""
    WITH ThematicDocs AS (
        SELECT node_id, node_type, name, doc_type, theme_id, latest_doc_date
        FROM (
            SELECT 'doc_' || SUBSTR(dl.sha256_hash, 1, 16) AS node_id,
                   'document' AS node_type,
                   dl.canonical_filename AS name,
                   dl.doc_type,
                   l.node_id AS theme_id,
                   COALESCE(dl.due_date, dl.doc_date) AS latest_doc_date,
                   ROW_NUMBER() OVER (
                       PARTITION BY l.node_id 
                       ORDER BY 
                           CASE WHEN EXISTS (SELECT 1 FROM action_items ai WHERE ai.sha256_hash = dl.sha256_hash AND ai.status = 'pending') THEN 1 ELSE 2 END ASC,
                           COALESCE(dl.due_date, dl.doc_date) DESC,
                           dl.sha256_hash ASC
                   ) AS theme_rank
            FROM document_ledger dl
            JOIN document_entity_links l ON dl.sha256_hash = l.sha256_hash AND l.role = 'CATEGORIZED_AS'
            WHERE l.node_id LIKE 'theme_%'
        )
        WHERE theme_rank <= 45
    )
    SELECT theme_id, COUNT(*), SUM(CASE WHEN doc_type = 'court_order' THEN 1 ELSE 0 END) as court_orders
    FROM ThematicDocs
    GROUP BY theme_id;
""")

print("Stratified ThematicDocs results:")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]} docs (court_orders: {r[2]})")

cur.execute("""
    WITH ThematicDocs AS (
        SELECT node_id, node_type, name, doc_type, theme_id, latest_doc_date
        FROM (
            SELECT 'doc_' || SUBSTR(dl.sha256_hash, 1, 16) AS node_id,
                   'document' AS node_type,
                   dl.canonical_filename AS name,
                   dl.doc_type,
                   l.node_id AS theme_id,
                   COALESCE(dl.due_date, dl.doc_date) AS latest_doc_date,
                   ROW_NUMBER() OVER (
                       PARTITION BY l.node_id 
                       ORDER BY 
                           CASE WHEN EXISTS (SELECT 1 FROM action_items ai WHERE ai.sha256_hash = dl.sha256_hash AND ai.status = 'pending') THEN 1 ELSE 2 END ASC,
                           COALESCE(dl.due_date, dl.doc_date) DESC,
                           dl.sha256_hash ASC
                   ) AS theme_rank
            FROM document_ledger dl
            JOIN document_entity_links l ON dl.sha256_hash = l.sha256_hash AND l.role = 'CATEGORIZED_AS'
            WHERE l.node_id LIKE 'theme_%'
        )
        WHERE theme_rank <= 45
    )
    SELECT name, latest_doc_date FROM ThematicDocs WHERE theme_id = 'theme_court_order' AND (LOWER(name) LIKE '%urteil%' OR LOWER(name) LIKE '%obergericht%' OR LOWER(name) LIKE '%bundesgericht%') LIMIT 10;
""")

print("\nCourt Order documents under theme_court_order:")
for r in cur.fetchall():
    print(f"  * {r[0]} ({r[1]})")
