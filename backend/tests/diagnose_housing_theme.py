import sqlite3
from backend.ledger.db import get_db_connection

def main():
    conn = get_db_connection()
    cur = conn.cursor()

    print("=== 1. ALL THEME NODES, DEGREE, AND DOC COUNT ===")
    cur.execute("""
        SELECT n.node_id, n.name,
               (SELECT COUNT(*) FROM knowledge_edges e WHERE e.source_id = n.node_id OR e.target_id = n.node_id) as degree,
               (SELECT COUNT(DISTINCT l.sha256_hash) FROM document_entity_links l WHERE l.node_id = n.node_id) as doc_count
        FROM knowledge_nodes n
        WHERE n.node_type = 'theme'
        ORDER BY doc_count DESC
    """)
    for r in cur.fetchall():
        print(f"{r['node_id']:<35} | Name: {r['name']:<32} | Degree: {r['degree']:<3} | Docs: {r['doc_count']}")

    print("\n=== 2. KNOWLEDGE EDGES INCIDENT TO ANY THEME ===")
    cur.execute("""
        SELECT source_id, relation_type, target_id, count(*) as cnt
        FROM knowledge_edges
        WHERE source_id LIKE 'theme_%' OR target_id LIKE 'theme_%'
        GROUP BY source_id, relation_type, target_id
    """)
    edges = cur.fetchall()
    if not edges:
        print("NO EDGES CONNECTED TO ANY THEME AT ALL!")
    else:
        for e in edges:
            print(f"{e['source_id']} --[{e['relation_type']}]--> {e['target_id']} (count: {e['cnt']})")

    print("\n=== 3. WHAT ARE THE 23 DOCUMENTS IN theme_real_estate_housing? ===")
    cur.execute("""
        SELECT dl.doc_type, dl.canonical_filename, COALESCE(fl.relative_path, '') as rel_path
        FROM document_entity_links del
        JOIN document_ledger dl ON del.sha256_hash = dl.sha256_hash
        LEFT JOIN file_locations fl ON dl.sha256_hash = fl.sha256_hash
        WHERE del.node_id = 'theme_real_estate_housing'
        GROUP BY dl.sha256_hash
        LIMIT 15
    """)
    for r in cur.fetchall():
        print(f"[{r['doc_type']}] {r['canonical_filename']} -> {r['rel_path']}")

    print("\n=== 4. SEARCHING FOR HOUSING-RELATED DOCUMENTS ACROSS THE LEDGER (BY PATH / FILENAME) ===")
    cur.execute("""
        SELECT dl.doc_type, COUNT(DISTINCT dl.sha256_hash) as cnt
        FROM document_ledger dl
        LEFT JOIN file_locations fl ON dl.sha256_hash = fl.sha256_hash
        WHERE lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%immo%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%wohn%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%miet%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%hypo%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%liegenschaft%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%nebenkosten%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%hausverwaltung%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%loyer%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%bail%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%regie%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%real_estate%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%housing%'
        GROUP BY dl.doc_type
        ORDER BY cnt DESC
    """)
    housing_path_rows = cur.fetchall()
    total_housing_paths = 0
    for r in housing_path_rows:
        print(f"doc_type: {r['doc_type']:<25} | count: {r['cnt']}")
        total_housing_paths += r['cnt']
    print(f"Total documents with housing keywords in path/filename: {total_housing_paths}")

    print("\n=== 5. WHAT THEMES ARE THOSE HOUSING-PATH DOCUMENTS CURRENTLY LINKED TO? ===")
    cur.execute("""
        SELECT COALESCE(del.node_id, 'NO_THEME') as theme_linked, COUNT(DISTINCT dl.sha256_hash) as doc_count
        FROM document_ledger dl
        LEFT JOIN file_locations fl ON dl.sha256_hash = fl.sha256_hash
        LEFT JOIN document_entity_links del ON dl.sha256_hash = del.sha256_hash AND del.node_id LIKE 'theme_%'
        WHERE lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%immo%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%wohn%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%miet%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%hypo%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%liegenschaft%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%nebenkosten%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%hausverwaltung%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%loyer%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%bail%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%regie%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%real_estate%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%housing%'
        GROUP BY theme_linked
        ORDER BY doc_count DESC
    """)
    for r in cur.fetchall():
        print(f"  {r['theme_linked']:<35} : {r['doc_count']} docs")

    print("\n=== 6. LEGAL DISPUTE DOCUMENTS RELATING TO REAL ESTATE / HOUSING / PROPERTY ACCESS ===")
    # Look for court_order, formal_correspondence, legal_contract with housing/property/access terms
    cur.execute("""
        SELECT dl.doc_type, COUNT(DISTINCT dl.sha256_hash) as cnt
        FROM document_ledger dl
        LEFT JOIN file_locations fl ON dl.sha256_hash = fl.sha256_hash
        JOIN document_entity_links del ON dl.sha256_hash = del.sha256_hash AND del.node_id = 'theme_legal_justice'
        WHERE lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%immo%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%wohn%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%miet%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%liegenschaft%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%zuger'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%steinhausen%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%zug%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%ausweisung%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%zutritt%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%accès%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%logement%'
        GROUP BY dl.doc_type
        ORDER BY cnt DESC
    """)
    dispute_housing_rows = cur.fetchall()
    total_dispute_housing = 0
    for r in dispute_housing_rows:
        print(f"dispute doc_type: {r['doc_type']:<25} | count: {r['cnt']}")
        total_dispute_housing += r['cnt']
    print(f"Total legal dispute documents concerning housing/property/access: {total_dispute_housing}")

    print("\n=== 7. FINANCIAL INVOICES & BANKING STATEMENTS RELATING TO HOUSING ===")
    cur.execute("""
        SELECT dl.doc_type, COUNT(DISTINCT dl.sha256_hash) as cnt
        FROM document_ledger dl
        LEFT JOIN file_locations fl ON dl.sha256_hash = fl.sha256_hash
        JOIN document_entity_links del ON dl.sha256_hash = del.sha256_hash AND del.node_id IN ('theme_taxation_accounting', 'theme_banking_finance')
        WHERE lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%immo%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%wohn%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%miet%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%hypo%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%liegenschaft%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%nebenkosten%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%zinsausweis%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%loyer%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%bail%'
        GROUP BY dl.doc_type
        ORDER BY cnt DESC
    """)
    for r in cur.fetchall():
        print(f"financial doc_type: {r['doc_type']:<25} | count: {r['cnt']}")


def  test_theme_knowledge_nodes():
    from backend.ledger.db import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()

    print('=== RELEVANT ENTITIES IN KNOWLEDGE_NODES ===')
    cur.execute('''
        SELECT node_id, node_type, name 
        FROM knowledge_nodes 
        WHERE lower(node_id) LIKE '%steinhausen%'
        OR lower(node_id) LIKE '%zug%'
        OR lower(node_id) LIKE '%muller%'
        OR lower(node_id) LIKE '%müller%'
        OR lower(node_id) LIKE '%lease%'
        OR lower(node_id) LIKE '%rent%'
        OR lower(node_id) LIKE '%housing%'
        OR lower(node_id) LIKE '%estate%'
        OR lower(node_id) LIKE '%immo%'
        OR lower(node_id) LIKE '%mortgage%'
        OR lower(node_id) LIKE '%court%'
        OR lower(node_id) LIKE '%gericht%'
        ORDER BY node_type, name
    ''')
    for r in cur.fetchall():
        print(f'[{r[1]}] {r[0]}: {r[2]}')


def  test_theme_contract_types():
    from backend.ledger.db import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute('''
        SELECT node_id, node_type, name 
        FROM knowledge_nodes 
        WHERE node_type IN ('location', 'organization', 'contract_type', 'financial_pillar', 'theme')
        AND (
            lower(node_id) LIKE '%steinhausen%'
            OR lower(node_id) LIKE '%zug%'
            OR lower(node_id) LIKE '%muller%'
            OR lower(node_id) LIKE '%müller%'
            OR lower(node_id) LIKE '%rent%'
            OR lower(node_id) LIKE '%mortgage%'
            OR lower(node_id) LIKE '%lease%'
            OR lower(node_id) LIKE '%housing%'
            OR lower(node_id) LIKE '%estate%'
            OR lower(node_id) LIKE '%kantonsgericht%'
            OR lower(node_id) LIKE '%obergericht%'
            OR lower(node_id) LIKE '%friedensrichter%'
            OR lower(node_id) LIKE '%schlichtungsbeh%'
        )
        ORDER BY node_type, name
    ''')
    for r in cur.fetchall():
        print(f'[{r[1]}] {r[0]}: {r[2]}')



if __name__ == "__main__":
    main()
    test_theme_knowledge_nodes()
    test_theme_contract_types()
