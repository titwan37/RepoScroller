import urllib.request
import json

def post(endpoint, payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        f'http://127.0.0.1:11434/api/{endpoint}',
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    res = urllib.request.urlopen(req, timeout=120)
    return json.loads(res.read())

print("Testing V1 embedding model: snowflake-arctic-embed:latest...")
post('embed', {
    'model': 'snowflake-arctic-embed:latest',
    'input': 'test prompt',
    'keep_alive': '24h'
})

print("Testing chat model: llama3.2:3b...")
post('chat', {
    'model': 'llama3.2:3b',
    'messages': [{'role': 'user', 'content': 'ping'}],
    'stream': False,
    'keep_alive': '24h',
    'options': {'num_ctx': 2048}
})

req = urllib.request.Request("http://127.0.0.1:11434/api/ps")
with urllib.request.urlopen(req) as resp:
    ps = json.loads(resp.read().decode('utf-8'))
    print("\n--- ACTIVE MODELS IN VRAM ---")
    for m in ps.get('models', []):
        size_mb = m.get('size_vram', 0) / (1024 * 1024)
        ctx = m.get('context_length', 'N/A')
        print(f" -> {m['name']:30} | {size_mb:7.1f} MB | Context: {ctx}")
