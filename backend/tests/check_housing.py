import sqlite3; conn = sqlite3.connect('backend/data/reposcroller_ledger.db'); c = conn.cursor(); print(c.execute('SELECT id, label, entity_type FROM knowledge_nodes WHERE id = ?', ('theme_real_estate_housing',)).fetchall()); print(c.execute('SELECT COUNT(*) FROM knowledge_edges WHERE source_id = ? OR target_id = ?', ('theme_real_estate_housing', 'theme_real_estate_housing')).fetchone()); print(c.execute('SELECT COUNT(*) FROM document_entity_links WHERE entity_id = ?', ('theme_real_estate_housing',)).fetchone())

import sqlite3; conn = sqlite3.connect('backend/data/reposcroller_ledger.db'); c = conn.cursor(); print([row[0] for row in c.execute('SELECT sql FROM sqlite_master WHERE type=\"table\"').fetchall() if row[0]])

import sqlite3
from backend.ledger.db import get_db_connection

conn = get_db_connection()
cur = conn.cursor()

print('=== 1. ALL THEME NODES, DEGREE, AND DOC COUNT ===')
cur.execute('''
    SELECT n.node_id, n.name,
           (SELECT COUNT(*) FROM knowledge_edges e WHERE e.source_id = n.node_id OR e.target_id = n.node_id) as degree,
           (SELECT COUNT(DISTINCT l.sha256_hash) FROM document_entity_links l WHERE l.node_id = n.node_id) as doc_count
    FROM knowledge_nodes n
    WHERE n.node_type = 'theme'
    ORDER BY doc_count DESC
''')
for r in cur.fetchall():
    print(f'{r[0]:<35} | Name: {r[1]:<32} | Degree: {r[2]:<3} | Docs: {r[3]}')

print('\n=== 2. KNOWLEDGE EDGES INCIDENT TO ANY THEME ===')
cur.execute('''
    SELECT source_id, relation_type, target_id, count(*)
    FROM knowledge_edges
    WHERE source_id LIKE \"theme_%\" OR target_id LIKE \"theme_%\"
    GROUP BY source_id, relation_type, target_id
''')
edges = cur.fetchall()
if not edges:
    print('NO EDGES CONNECTED TO ANY THEME AT ALL!')
else:
    for e in edges:
        print(f'{e[0]} --[{e[1]}]--> {e[2]} (count: {e[3]})')

print('\n=== 3. WHAT ARE THE 23 DOCUMENTS IN theme_real_estate_housing? ===')
cur.execute('''
    SELECT dl.doc_type, dl.canonical_filename, dl.relative_path
    FROM document_entity_links del
    JOIN document_ledger dl ON del.sha256_hash = dl.sha256_hash
    WHERE del.node_id = 'theme_real_estate_housing'
    LIMIT 10
''')
for r in cur.fetchall():
    print(f'[{r[0]}] {r[1]} -> {r[2]}')

print('\n=== 4. SEARCHING FOR HOUSING-RELATED DOCUMENTS ACROSS THE LEDGER ===')
# Keywords: rent, miete, mietzins, wohnung, immobilien, immo, liegenschaft, hypothek, zinsausweis, nebenkosten, verwaltung, bail, loyer
cur.execute('''
    SELECT doc_type, COUNT(*) 
    FROM document_ledger
    WHERE lower(relative_path) LIKE '%immo%'
       OR lower(relative_path) LIKE '%wohn%'
       OR lower(relative_path) LIKE '%miet%'
       OR lower(relative_path) LIKE '%hypo%'
       OR lower(relative_path) LIKE '%liegenschaft%'
       OR lower(relative_path) LIKE '%nebenkosten%'
       OR lower(relative_path) LIKE '%hausverwaltung%'
       OR lower(relative_path) LIKE '%loyer%'
       OR lower(relative_path) LIKE '%bail%'
       OR lower(relative_path) LIKE '%regie%'
    GROUP BY doc_type
    ORDER BY COUNT(*) DESC
''')
for r in cur.fetchall():
    print(f'doc_type: {r[0]:<25} | count: {r[1]}')



def test_housing_3d():
    from backend.ledger.repository import DocumentRepository
    from backend.ledger.graph_store import PropertyGraphStore
    repo = DocumentRepository()
    store = PropertyGraphStore(repo)
    res = store.get_3d_knowledge_universe(layout='thematic', limit=500)

    housing_node = next((n for n in res['nodes'] if n['id'] == 'theme_real_estate_housing'), None)
    print('--- HOUSING NODE IN 3D THEMATIC UNIVERSE ---')
    if housing_node:
        for k, v in housing_node.items():
            print(f'  {k}: {v}')
    else:
        print('NOT FOUND!')

    print('\n--- EDGES INCIDENT TO THEME_REAL_ESTATE_HOUSING IN 3D SCENE ---')
    incident_edges = [e for e in res['edges'] if e['source'] == 'theme_real_estate_housing' or e['target'] == 'theme_real_estate_housing']
    print(f'Total incident edges: {len(incident_edges)}')
    for e in incident_edges[:10]:
        print(f'  {e[\"source\"]} --[{e[\"relation\"]}]--> {e[\"target\"]}')


def test_housing_3d_detailed():
    """
    Diagnose why theme_real_estate_housing is missing from 3D thematic universe.
    """
    from backend.ledger.db import get_db_connection
    from backend.ledger.graph_store import PropertyGraphStore
    from backend.ledger.repository import DocumentRepository
    import json
    
    print('=== 1. BASIC THEME COUNTS ===')
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT node_id, count(*) FROM document_entity_links WHERE node_id LIKE 'theme_%' GROUP BY node_id ORDER BY count(*) DESC")
    for r in cur.fetchall():
        print(f'  {r[0]}: {r[1]}')
        
    print('\n=== 2. HOUSING NODE EXIST CHECK ===')
    cur.execute("SELECT * FROM knowledge_nodes WHERE node_id = 'theme_real_estate_housing'")
    print('Exists in nodes table?', cur.fetchone() is not None)
    
    cur.execute("SELECT * FROM document_entity_links WHERE node_id = 'theme_real_estate_housing'")
    print('Has links in doc-entity table?', cur.fetchone() is not None)
    
    print('\n=== 3. ALL EDGES FOR THEME_REAL_ESTATE_HOUSING ===')
    cur.execute("SELECT source_id, relation_type, target_id FROM knowledge_edges WHERE source_id = 'theme_real_estate_housing' OR target_id = 'theme_real_estate_housing'")
    edges = cur.fetchall()
    print(f'Found {len(edges)} edges')
    for e in edges:
        print(f'  {e[0]} --[{e[1]}]--> {e[2]}')
        
    print('\n=== 4. KNOWLEDGE GRAPH EXPORT (raw from DB) ===')
    graph = {"nodes": [], "edges": []}
    # Get all nodes with 'theme' or 'sub_theme'
    cur.execute("SELECT node_id, name, node_type, properties FROM knowledge_nodes WHERE node_type IN ('theme', 'sub_theme')")
    for (nid, name, node_type, props) in cur.fetchall():
        graph["nodes"].append({
            "id": nid,
            "name": name,
            "type": node_type,
            "properties": json.loads(props) if props else {}
        })
    # Get all edges connected to themes
    cur.execute("SELECT source_id, target_id, relation_type, properties FROM knowledge_edges WHERE source_id LIKE 'theme_%' OR target_id LIKE 'theme_%'")
    for (src, tgt, rel, props) in cur.fetchall():
        graph["edges"].append({
            "source": src,
            "target": tgt,
            "relation": rel,
            "properties": json.loads(props) if props else {}
        })
    
    # Save for inspection
    with open("debug_graph.json", "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)
    print('Wrote debug_graph.json')
    
    print('\n=== 5. 3D UNIVERSE GENERATION (THEMATIC LAYOUT) ===')
    repo = DocumentRepository()
    store = PropertyGraphStore(repo)
    # Force small limit to see everything
    res = store.get_3d_knowledge_universe(layout="thematic", limit=100)
    
    print(f'Nodes in 3D scene: {len(res["nodes"])}')
    print(f'Edges in 3D scene: {len(res["edges"])}')
    
    print('\n=== 6. SEARCH WITHIN 3D SCENE FOR HOUSING ===')
    found = False
    for n in res["nodes"]:
        if n["id"] == "theme_real_estate_housing":
            print('!!! FOUND IN 3D SCENE !!!')
            print(json.dumps(n, indent=2))
            found = True
    
    if not found:
        print('theme_real_estate_housing IS MISSING FROM 3D SCENE')
        print('IDs present in 3D:', [n["id"] for n in res["nodes"][:20]])


if __name__ == "__main__":
    test_housing_3d()
    test_housing_3d_detailed()