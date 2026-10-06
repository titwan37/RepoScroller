
from reposcroller.ledger.repository import DocumentRepository
r = DocumentRepository()
cur = r.conn.cursor()
cur.execute('SELECT node_type, count(*) as cnt FROM knowledge_nodes GROUP BY node_type')
for x in cur.fetchall():
    print(dict(x))

import urllib.request, json

res = json.loads(urllib.request.urlopen("http://localhost:8090/api/v1/sidecar/graph-3d").read())
cluster_list = res.get('clusters', res.get('cluster_definitions', []))
print({k: v for k, v in res['stats'].items() if k != 'dimensionality'})
for c in cluster_list:
    print("{:<35} | {:<10} | {:<10} | {:<10} | {:.1f}%".format(c['name'], c['rendered_count'], c['quota'], c['total_in_db'], c['representation_pct']))


from reposcroller.ledger.graph_store import PropertyGraphStore
from reposcroller.ledger.repository import DocumentRepository

gs = PropertyGraphStore(DocumentRepository())
res = gs.get_3d_knowledge_universe(1000)
[print(c['archetype'], 'Rendered:', c['rendered_count'], 'Total:', c['total_in_db'], 'Pct:', c['representation_pct'], 'Capped:', c['is_capped']) for c in res['clusters']]