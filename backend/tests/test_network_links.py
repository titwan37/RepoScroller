import sqlite3
conn = sqlite3.connect('backend/data/reposcroller_ledger.db')
cur = conn.cursor()
cur.execute('SELECT node_id, node_type, name FROM knowledge_nodes WHERE node_id LIKE \"%/%\";')
print('With /:', len(cur.fetchall()))
cur.execute('SELECT node_id, node_type, name FROM knowledge_nodes WHERE node_id LIKE \"% %\" LIMIT 5;')
print('With space:', cur.fetchall())
cur.execute('SELECT node_id FROM knowledge_nodes WHERE node_id LIKE \"%.%\" LIMIT 5;')
print('With dot:', cur.fetchall())