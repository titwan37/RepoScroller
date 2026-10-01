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
    res = urllib.request.urlopen(req, timeout=60)
    return json.loads(res.read())

def call_get(endpoint):
    req = urllib.request.Request(f'http://127.0.0.1:11434/api/{endpoint}')
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read())

print("1. Calling embed model...")
r1 = call_post('embed', {
    'model': 'snowflake-arctic-embed2:latest',
    'input': 'test embeddings',
    'keep_alive': '24h'
})
print("Embed loaded. Current ps:")
ps1 = call_get('ps')
for m in ps1.get('models', []):
    print(f"  - {m['name']} (VRAM: {m.get('size_vram', 0)/(1024*1024):.1f} MB)")

print("\n2. Calling chat model...")
r2 = call_post('chat', {
    'model': 'llama3.2:3b',
    'messages': [{'role': 'user', 'content': 'hi'}],
    'stream': False,
    'keep_alive': '24h'
})
print("Chat loaded. Current ps:")
ps2 = call_get('ps')
for m in ps2.get('models', []):
    print(f"  - {m['name']} (VRAM: {m.get('size_vram', 0)/(1024*1024):.1f} MB)")
