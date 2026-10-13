import sys
sys.path.insert(0, r"c:\Dev\RepoScroller")

from backend.ledger.db import get_db_connection

conn = get_db_connection()
cur = conn.cursor()

# Test theme matching for "Court Order", "court_order", "urteil":
test_inputs = ["Court Order", "court_order", "court", "urteil"]

for inp in test_inputs:
    clean = inp.lower().strip()
    clean_under = clean.replace(" ", "_")
    clean_space = clean.replace("_", " ")

    # Themes
    cur.execute("""
        SELECT node_id, name FROM knowledge_nodes
        WHERE node_type = 'theme' AND (
            LOWER(node_id) LIKE ? OR LOWER(name) LIKE ? OR
            LOWER(node_id) LIKE ? OR LOWER(name) LIKE ? OR
            LOWER(node_id) LIKE ? OR LOWER(name) LIKE ?
        )
    """, (f"%{clean}%", f"%{clean}%", f"%{clean_under}%", f"%{clean_under}%", f"%{clean_space}%", f"%{clean_space}%"))
    matched_themes = cur.fetchall()

    # Doc types
    cur.execute("SELECT DISTINCT doc_type FROM document_ledger WHERE LOWER(doc_type) = ? OR LOWER(doc_type) = ?", (clean, clean_under))
    matched_doctypes = cur.fetchall()

    # Doc filenames / text
    cur.execute("SELECT COUNT(*) FROM document_ledger WHERE LOWER(canonical_filename) LIKE ? OR LOWER(text_snippet) LIKE ?", (f"%{clean}%", f"%{clean}%"))
    matched_docs_cnt = cur.fetchone()[0]

    print(f"\nQuery: '{inp}'")
    print("  Themes matched:", [r[0] for r in matched_themes])
    print("  Doc types matched:", [r[0] for r in matched_doctypes])
    print("  Docs matching filename/text:", matched_docs_cnt)
