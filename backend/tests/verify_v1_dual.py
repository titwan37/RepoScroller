import urllib.request
import json
import time

def post(endpoint, payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        f'http://127.0.0.1:11434/api/{endpoint}',
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    res = urllib.request.urlopen(req, timeout=60)
    return json.loads(res.read())

print("1. Loading V1 embedding model 'snowflake-arctic-embed:latest'...")
t0 = time.time()
post('embed', {
    'model': 'snowflake-arctic-embed:latest',
    'input': 'RepoScroller probe',
    'keep_alive': '24h'
})
print(f"   Done in {(time.time()-t0)*1000:.0f}ms")

print("2. Loading chat model 'llama3.2:3b' (num_ctx=2048)...")
t0 = time.time()
post('chat', {
    'model': 'llama3.2:3b',
    'messages': [{'role': 'user', 'content': 'hi'}],
    'stream': False,
    'keep_alive': '24h',
    'options': {'num_ctx': 2048}
})
print(f"   Done in {(time.time()-t0)*1000:.0f}ms")

print("\n--- ACTIVE MODELS IN VRAM (/api/ps) ---")
req = urllib.request.Request("http://127.0.0.1:11434/api/ps")
with urllib.request.urlopen(req) as resp:
    ps = json.loads(resp.read().decode('utf-8'))
    for m in ps.get('models', []):
        size_mb = m.get('size_vram', 0) / (1024 * 1024)
        ctx = m.get('context_length', 'N/A')
        print(f" -> {m['name']:30} | {size_mb:7.1f} MB | Context: {ctx} | 100% GPU")
