import json
import sqlite3
from email import contentmanager

def check_entities():
    conn = sqlite3.connect('../data/reposcroller_ledger.db'); 
    cur = conn.cursor(); 
    cur.execute('SELECT node_type, count(*) FROM knowledge_nodes GROUP BY node_type'); 
    print('Node types:', cur.fetchall()); 
    cur.execute('SELECT node_id, node_type, name FROM knowledge_nodes LIMIT 10'); 
    print('Sample nodes:', cur.fetchall()); 
    cur.execute('SELECT count(*) FROM document_entity_links'); 
    print('Links count:', cur.fetchone());

    cur = conn.cursor();
    cur.execute('SELECT dl.sha256_hash, dl.canonical_filename, l.node_id, n.name, n.node_type FROM document_ledger dl JOIN document_entity_links l ON dl.sha256_hash = l.sha256_hash JOIN knowledge_nodes n ON l.node_id = n.node_id LIMIT 10'); 
    print(cur.fetchall())  

    conn = sqlite3.connect("backend/data/reposcroller_ledger.db")
    cur = conn.cursor(); 
    cur.execute("SELECT count(*) FROM knowledge_nodes WHERE node_type = \"document\" OR node_id LIKE \"doc_%\";"); 
    print("Doc nodes:", cur.fetchone()); 
    cur.execute("SELECT count(*) FROM document_ledger;"); 
    print("Total docs:", cur.fetchone())


    import sqlite3
    conn = sqlite3.connect("backend/data/reposcroller_ledger.db")
    cur = conn.cursor()
    cur.execute("""
        SELECT l1.sha256_hash, l1.node_id, l2.node_id
        FROM document_entity_links l1
        JOIN document_entity_links l2 ON l1.sha256_hash = l2.sha256_hash
        WHERE l1.node_id LIKE "%zkb%" AND l2.node_id LIKE "%zurich%"
        LIMIT 5;
    """)
    print("Shared docs between ZKB and Zurich:", cur.fetchall())



conn = sqlite3.connect("backend/data/reposcroller_ledger.db")
cur = conn.cursor()

# Test location=zurich & org=zkb
loc_str = "zurich"
org_str = "zkb"

cur.execute("SELECT node_id FROM knowledge_nodes WHERE node_type = \"location\" AND (LOWER(name) LIKE ? OR LOWER(node_id) LIKE ?)", (f"%{loc_str}%", f"%{loc_str}%"))
loc_nodes = [r[0] for r in cur.fetchall()]

cur.execute("SELECT node_id FROM knowledge_nodes WHERE node_type = \"organization\" AND (LOWER(name) LIKE ? OR LOWER(node_id) LIKE ?)", (f"%{org_str}%", f"%{org_str}%"))
org_nodes = [r[0] for r in cur.fetchall()]

print("Found loc_nodes:", loc_nodes)
print("Found org_nodes:", org_nodes)

# Find shared documents
placeholders_loc = ",".join("?" for _ in loc_nodes)
placeholders_org = ",".join("?" for _ in org_nodes)

cur.execute(f"""
    SELECT DISTINCT l1.sha256_hash
    FROM document_entity_links l1
    JOIN document_entity_links l2 ON l1.sha256_hash = l2.sha256_hash
    WHERE l1.node_id IN ({placeholders_loc}) AND l2.node_id IN ({placeholders_org})
""", loc_nodes + org_nodes)
shared_docs = [r[0] for r in cur.fetchall()]
print("Shared docs count:", len(shared_docs))

# Find all entities in those shared docs
if shared_docs:
    p_docs = ",".join("?" for _ in shared_docs)
    cur.execute(f"SELECT DISTINCT node_id FROM document_entity_links WHERE sha256_hash IN ({p_docs})", shared_docs)
    connecting_entities = [r[0] for r in cur.fetchall()]
    print("Connecting entities count:", len(connecting_entities))
