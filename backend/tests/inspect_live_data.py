import urllib.request
import ssl
import json

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

url = 'https://afastudio.ch/reposcroller/api/v1/sidecar/graph-3d?limit=1000&layout=thematic'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
    content = resp.read().decode('utf-8')
    data = json.loads(content)

print('Nodes count:', len(data.get('nodes', [])))
print('Edges count:', len(data.get('edges', [])))
print('Clusters count:', len(data.get('clusters', [])))

nodes = data.get('nodes', [])
quotes_list = []
for n in nodes:
    name = n.get('name', '')
    node_id = str(n.get('id', ''))
    if "'" in name or '"' in name or "'" in node_id or '"' in node_id:
        quotes_list.append((node_id, name))

print(f'Total nodes with quotes: {len(quotes_list)}')
for p in quotes_list[:20]:
    print('  ', p)

clusters = data.get('clusters', [])
for c in clusters:
    c_name = c.get('name', '')
    c_id = c.get('id')
    print(f"Cluster: id={c_id} (type {type(c_id)}) name={c_name}")
