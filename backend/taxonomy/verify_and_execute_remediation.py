"""Remediation and verification script for reposcroller_ledger.db.

Ensures:
1. Document fbc2f2552ebd... (2020-12-03-Zuger-Polizei-Einvernahmeprotokoll-häuslicher-Gewalt...)
   is mapped to court_order / theme_legal_justice.
2. Purges household-violence from global_taxonomy.
3. Deletes theme_household_violence from knowledge_nodes and knowledge_edges.
4. Consolidates the 4 duplicate double-prefixed themes:
   - theme_theme_career_employment -> theme_career_employment
   - theme_theme_legal_justice -> theme_legal_justice
   - theme_theme_education_training -> theme_education_training
   - theme_theme_taxation_accounting -> theme_taxation_accounting
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("backend/data/reposcroller_ledger.db")

def main():
    print(f"Connecting to: {DB_PATH.resolve()}")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("BEGIN TRANSACTION;")

    try:
        # 1. Remap document fbc2f2552ebd...
        doc_hash = "fbc2f2552ebd9de5ef63569511e69811a38abcc4656c6e45f49be98039124bce"
        cur.execute("""
            UPDATE document_ledger
            SET doc_type = 'court_order'
            WHERE sha256_hash = ?;
        """, (doc_hash,))
        print(f"1. Updated document_ledger for {doc_hash[:12]}: rows affected = {cur.rowcount}")

        # Update document_entity_links for this doc
        cur.execute("""
            UPDATE document_entity_links
            SET node_id = 'theme_legal_justice'
            WHERE sha256_hash = ? AND node_id IN ('theme_household_violence', 'document_category_household_violence');
        """, (doc_hash,))
        print(f"   Updated document_entity_links for {doc_hash[:12]}: rows affected = {cur.rowcount}")

        # Also update any other links pointing to theme_household_violence
        cur.execute("""
            UPDATE document_entity_links
            SET node_id = 'theme_legal_justice'
            WHERE node_id = 'theme_household_violence';
        """)
        print(f"   Updated any other links to theme_household_violence: rows affected = {cur.rowcount}")

        # 2. Purge household-violence from global_taxonomy
        cur.execute("DELETE FROM global_taxonomy WHERE category_id = 'household-violence';")
        print(f"2. Purged household-violence from global_taxonomy: rows affected = {cur.rowcount}")

        # 3. Delete theme_household_violence from knowledge_nodes and knowledge_edges
        cur.execute("DELETE FROM knowledge_nodes WHERE node_id = 'theme_household_violence';")
        print(f"3. Deleted theme_household_violence from knowledge_nodes: rows affected = {cur.rowcount}")
        cur.execute("DELETE FROM knowledge_edges WHERE source_id = 'theme_household_violence' OR target_id = 'theme_household_violence';")
        print(f"   Deleted theme_household_violence from knowledge_edges: rows affected = {cur.rowcount}")

        # 4. Consolidate the 4 duplicate double-prefixed themes
        double_prefix_map = {
            'theme_theme_career_employment': 'theme_career_employment',
            'theme_theme_legal_justice': 'theme_legal_justice',
            'theme_theme_education_training': 'theme_education_training',
            'theme_theme_taxation_accounting': 'theme_taxation_accounting',
        }

        print("4. Consolidating duplicate double-prefixed themes:")
        for old_id, new_id in double_prefix_map.items():
            cur.execute("UPDATE document_entity_links SET node_id = ? WHERE node_id = ?;", (new_id, old_id))
            links_affected = cur.rowcount
            cur.execute("UPDATE OR IGNORE knowledge_edges SET target_id = ? WHERE target_id = ?;", (new_id, old_id))
            edges_affected = cur.rowcount
            cur.execute("DELETE FROM knowledge_edges WHERE target_id = ? OR source_id = ?;", (old_id, old_id))
            cur.execute("DELETE FROM knowledge_nodes WHERE node_id = ?;", (old_id,))
            nodes_deleted = cur.rowcount
            print(f"   - {old_id} -> {new_id}: links={links_affected}, edges={edges_affected}, nodes_deleted={nodes_deleted}")

        conn.commit()
        print("\nAll changes committed successfully!\n")

        # --- VERIFICATION ---
        print("=== VERIFICATION SUMMARY ===")
        # Check document
        cur.execute("SELECT sha256_hash, doc_type, canonical_filename FROM document_ledger WHERE sha256_hash = ?;", (doc_hash,))
        doc_row = cur.fetchone()
        print(f"Document record: {doc_row}")

        cur.execute("SELECT node_id, role FROM document_entity_links WHERE sha256_hash = ?;", (doc_hash,))
        links = cur.fetchall()
        print(f"Document entity links ({len(links)}): {links}")

        # Check global_taxonomy
        cur.execute("SELECT category_id, name_en FROM global_taxonomy WHERE category_id = 'household-violence';")
        hv_tax = cur.fetchall()
        print(f"global_taxonomy 'household-violence' entries: {hv_tax} (should be empty)")

        # Check knowledge_nodes
        cur.execute("SELECT node_id, name FROM knowledge_nodes WHERE node_id = 'theme_household_violence';")
        hv_node = cur.fetchall()
        print(f"knowledge_nodes 'theme_household_violence' entries: {hv_node} (should be empty)")

        cur.execute("SELECT node_id, name FROM knowledge_nodes WHERE node_id LIKE 'theme_theme%';")
        double_nodes = cur.fetchall()
        print(f"knowledge_nodes 'theme_theme_*' entries: {double_nodes} (should be empty)")

        cur.execute("SELECT node_id, name FROM knowledge_nodes WHERE node_type = 'theme' ORDER BY node_id;")
        themes = cur.fetchall()
        print(f"\nRemaining Theme nodes ({len(themes)}):")
        for t in themes:
            print(f"  - {t[0]}: {t[1]}")

    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()
