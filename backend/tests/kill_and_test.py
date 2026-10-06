import subprocess
import time
import os
import urllib.request
import json

print("1. Killing all ollama processes including Windows System Tray app...")
subprocess.run(["taskkill", "/F", "/IM", "ollama app.exe"], capture_output=True)
subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"], capture_output=True)
time.sleep(2)

print("2. Starting fresh ollama server with OLLAMA_MAX_LOADED_MODELS=3...")
env = os.environ.copy()
env["OLLAMA_HOST"] = "0.0.0.0:11434"
env["OLLAMA_MAX_LOADED_MODELS"] = "3"
env["OLLAMA_NUM_PARALLEL"] = "4"
env["OLLAMA_KEEP_ALIVE"] = "24h"
env["OLLAMA_FLASH_ATTENTION"] = "1"

proc = subprocess.Popen(["ollama", "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

for i in range(15):
    time.sleep(1)
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=2) as r:
            if r.status == 200:
                print(f"Ollama is ONLINE (attempt {i+1})")
                break
    except Exception:
        pass

def post(endpoint, payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        f'http://127.0.0.1:11434/api/{endpoint}',
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    res = urllib.request.urlopen(req, timeout=120)
    return json.loads(res.read())

print("\n3. Loading embed model (snowflake-arctic-embed2:latest)...")
t0 = time.time()
r_emb = post('embed', {
    'model': 'snowflake-arctic-embed2:latest',
    'input': 'RepoScroller warm up probe',
    'keep_alive': '24h',
    'options': {'num_ctx': 2048}
})
print(f"   -> Done in {(time.time()-t0)*1000:.0f}ms")

print("4. Loading chat model (llama3.2:3b)...")
t0 = time.time()
r_chat = post('chat', {
    'model': 'llama3.2:3b',
    'messages': [{'role': 'user', 'content': 'ping'}],
    'stream': False,
    'keep_alive': '24h',
    'options': {'num_ctx': 2048}
})
print(f"   -> Done in {(time.time()-t0)*1000:.0f}ms")

print("\n========================================================")
print(" ACTIVE MODELS IN VRAM (/api/ps):")
print("========================================================")
req = urllib.request.Request("http://127.0.0.1:11434/api/ps")
with urllib.request.urlopen(req) as resp:
    ps = json.loads(resp.read().decode('utf-8'))
    for m in ps.get('models', []):
        size_mb = m.get('size_vram', 0) / (1024 * 1024)
        ctx = m.get('context_length', 'N/A')
        print(f" -> {m['name']:35} | {size_mb:7.1f} MB | Context: {ctx} | 100% GPU")
print("========================================================")
