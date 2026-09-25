import urllib.request
import json

def call_post(endpoint, payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        f'http://127.0.0.1:11434/api/{endpoint}',
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    res = urllib.request.urlopen(req, timeout=60)
    return json.loads(res.read())

def call_get(endpoint):
    req = urllib.request.Request(f'http://127.0.0.1:11434/api/{endpoint}')
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read())

print("1. Loading embedding model with num_ctx=2048...")
call_post('embed', {
    'model': 'snowflake-arctic-embed2:latest',
    'input': 'testing embedding memory footprint',
    'keep_alive': '24h',
    'options': {
        'num_ctx': 2048
    }
})

print("2. Loading chat model with num_ctx=2048...")
call_post('chat', {
    'model': 'llama3.2:3b',
    'messages': [{'role': 'user', 'content': 'hi'}],
    'stream': False,
    'keep_alive': '24h',
    'options': {
        'num_ctx': 2048
    }
})

print("\n3. Inspecting active models in VRAM (/api/ps):")
ps = call_get('ps')
for m in ps.get('models', []):
    size_mb = m.get('size_vram', 0) / (1024 * 1024)
    ctx = m.get('context_length', 'N/A')
    print(f" -> Model: {m['name']} | VRAM: {size_mb:.1f} MB | Context: {ctx}")
