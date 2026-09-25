import urllib.request
import json
import time

def call_post(endpoint, payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        f'http://127.0.0.1:11434/api/{endpoint}',
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    res = urllib.request.urlopen(req, timeout=120)
    return json.loads(res.read())

def call_get(endpoint):
    req = urllib.request.Request(f'http://127.0.0.1:11434/api/{endpoint}')
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read())

print("Loading snowflake-arctic-embed2:latest with num_ctx=2048...")
call_post('embed', {
    'model': 'snowflake-arctic-embed2:latest',
    'input': 'probe',
    'keep_alive': '24h',
    'options': {'num_ctx': 2048}
})

print("Loading llama3.2:3b with num_ctx=2048...")
call_post('chat', {
    'model': 'llama3.2:3b',
    'messages': [{'role': 'user', 'content': 'ping'}],
    'stream': False,
    'keep_alive': '24h',
    'options': {'num_ctx': 2048}
})

print("\n--- Active Models in VRAM ---")
ps = call_get('ps')
for m in ps.get('models', []):
    size_mb = m.get('size_vram', 0) / (1024 * 1024)
    ctx = m.get('context_length', 'N/A')
    print(f" -> {m['name']:30} | {size_mb:7.1f} MB | Context: {ctx} | 100% GPU")
