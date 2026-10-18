import sys
sys.path.insert(0, r"c:\Dev\RepoScroller")
import sqlite3, json
from backend.config import settings
conn = sqlite3.connect(settings.DB_PATH)
c = conn.cursor()
c.execute("SELECT node_id, node_type, name, properties_json FROM knowledge_nodes WHERE name LIKE \"%109%\" AND node_type = \"statute\"")
for r in c.fetchall():
    print("Node:", r[0], r[1], r[2], r[3])