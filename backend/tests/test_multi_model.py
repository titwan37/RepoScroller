import urllib.request
import json

def call_get(endpoint):
    req = urllib.request.Request(f'http://127.0.0.1:11434/api/{endpoint}')
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read())

def call_post(endpoint, payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        f'http://127.0.0.1:11434/api/{endpoint}',
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    res = urllib.request.urlopen(req, timeout=60)
    return json.loads(res.read())

print("Current /api/ps:")
ps = call_get('ps')
for m in ps.get('models', []):
    print(f" -> {m.get('name')} | VRAM: {m.get('size_vram')} bytes")
