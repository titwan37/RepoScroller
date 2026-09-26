import subprocess
import time
import os
import urllib.request
import json

print("1. Terminating any running ollama processes...")
subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"], capture_output=True)
subprocess.run(["taskkill", "/F", "/IM", "ollama app.exe"], capture_output=True)
time.sleep(2)

print("2. Launching fresh Ollama server with explicit OLLAMA_MAX_LOADED_MODELS=3...")
env = os.environ.copy()
env["OLLAMA_HOST"] = "0.0.0.0:11434"
env["OLLAMA_MAX_LOADED_MODELS"] = "3"
env["OLLAMA_NUM_PARALLEL"] = "4"
env["OLLAMA_KEEP_ALIVE"] = "24h"
env["OLLAMA_FLASH_ATTENTION"] = "1"

server_proc = subprocess.Popen(
    ["ollama", "serve"],
    env=env,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
)

print("Waiting for server to become ready...")
for i in range(15):
    time.sleep(1)
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                print(f"Server is ONLINE after {i+1}s!")
                break
    except Exception:
        pass

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

print("\n3. Loading embedding model (num_ctx=2048)...")
call_post('embed', {
    'model': 'snowflake-arctic-embed2:latest',
    'input': 'RepoScroller sovereign LAN CUDA embedding node warm-up probe',
    'keep_alive': '24h',
    'options': {'num_ctx': 2048}
})

print("4. Loading chat model (num_ctx=2048)...")
call_post('chat', {
    'model': 'llama3.2:3b',
    'messages': [{'role': 'user', 'content': 'ping'}],
    'stream': False,
    'keep_alive': '24h',
    'options': {'num_ctx': 2048}
})

print("\n5. Checking active models in VRAM (/api/ps):")
ps = call_get('ps')
for m in ps.get('models', []):
    size_mb = m.get('size_vram', 0) / (1024 * 1024)
    ctx = m.get('context_length', 'N/A')
    print(f" -> Model: {m['name']} | VRAM: {size_mb:.1f} MB | Context: {ctx} | Processor: {m.get('details')}")
