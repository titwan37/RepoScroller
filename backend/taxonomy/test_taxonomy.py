import sqlite3
from backend.config import settings

def test_top_categories():
    conn = sqlite3.connect(settings.DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT taxonomy_version, count(*) FROM document_ledger GROUP BY taxonomy_version")
    print("Ledger taxonomy versions:", cur.fetchall())

    cur.execute("SELECT * FROM taxonomy_versions")
    print("Taxonomy versions table:", cur.fetchall())

    cur.execute("SELECT count(*) FROM global_taxonomy")
    print("Global taxonomy count:", cur.fetchone()[0])

    cur.execute("SELECT count(*) FROM knowledge_nodes WHERE node_type='theme'")
    print("Theme nodes count:", cur.fetchone()[0])

    conn = sqlite3.connect(settings.DB_PATH); cur = conn.cursor();
    cur.execute('SELECT node_id, count(*) FROM document_entity_links WHERE role=\'CATEGORIZED_AS\' GROUP BY node_id ORDER BY count(*) DESC');
    [print(r) for r in cur.fetchall()]

def test_taxonomy_versions():
    from backend.ledger.db import get_db_connection

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM taxonomy_versions WHERE version=\'v1.1.0\'" )
    print(cur.fetchone())

def test_taxonomy_manager():
    from backend.ai.taxonomy import TaxonomyManager
    from backend.ledger.db import get_db_connection

    mgr = TaxonomyManager(get_db_connection())

    res = mgr.sync_from_skill()
    print("Sync Result:", res)



if __name__ == "__main__":
    test_taxonomy_versions()
    test_top_categories()
    test_taxonomy_manager()
