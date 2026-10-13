import sys
sys.path.insert(0, r"c:\Dev\RepoScroller")

from backend.ledger.db import get_db_connection

conn = get_db_connection()
cur = conn.cursor()

# Test partitioned query:
cur.execute("""
    WITH RankedDocs AS (
        SELECT 'doc_' || SUBSTR(dl.sha256_hash, 1, 16) AS node_id,
               'document' AS node_type,
               dl.canonical_filename AS name,
               dl.doc_type,
               l.node_id AS theme_id,
               COALESCE(dl.due_date, dl.doc_date) AS effective_date,
               ROW_NUMBER() OVER (
                   PARTITION BY l.node_id 
                   ORDER BY 
                       CASE WHEN EXISTS (SELECT 1 FROM action_items ai WHERE ai.sha256_hash = dl.sha256_hash AND ai.status = 'pending') THEN 1 ELSE 2 END ASC,
                       COALESCE(dl.due_date, dl.doc_date) DESC
               ) AS rank_in_theme
        FROM document_ledger dl
        JOIN document_entity_links l ON dl.sha256_hash = l.sha256_hash AND l.role = 'CATEGORIZED_AS'
        WHERE l.node_id LIKE 'theme_%'
    )
    SELECT theme_id, COUNT(*), SUM(CASE WHEN LOWER(name) LIKE '%urteil%' THEN 1 ELSE 0 END) AS urteil_count
    FROM RankedDocs
    WHERE rank_in_theme <= 50
    GROUP BY theme_id;
""")

print("Documents per theme with stratified sampling (max 50 per theme):")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]} docs (Urteil count: {r[2]})")

cur.execute("""
    WITH RankedDocs AS (
        SELECT dl.canonical_filename, dl.doc_date, l.node_id AS theme_id,
               ROW_NUMBER() OVER (PARTITION BY l.node_id ORDER BY COALESCE(dl.due_date, dl.doc_date) DESC) AS rank
        FROM document_ledger dl
        JOIN document_entity_links l ON dl.sha256_hash = l.sha256_hash AND l.role = 'CATEGORIZED_AS'
        WHERE l.node_id = 'theme_court_order'
    )
    SELECT canonical_filename, doc_date FROM RankedDocs WHERE rank <= 10;
""")
print("\nTop 10 Court Order documents in theme_court_order:")
for r in cur.fetchall():
    print(f"  - {r[0]} ({r[1]})")
