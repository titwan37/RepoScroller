import pytest
import httpx
import time
from typing import List

# Remote PC2 Node URL
PC2_URL = "http://NITRO-AN51755:11434"

def test_ollama_tags():
    """Verify PC2 Ollama is reachable and models are loaded."""
    try:
        r = httpx.get(f"{PC2_URL}/api/tags", timeout=5.0)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        
        models = [m.get("name") for m in r.json().get("models", [])]
        assert len(models) > 0, "No models found on PC2"
        
        # Verify our required models are present
        assert any(m.startswith("llama3.1:8b") for m in models), "llama3.1:8b not found on PC2"
        assert any(m.startswith("snowflake-arctic-embed2") for m in models), "snowflake-arctic-embed2 not found on PC2"
    except httpx.ConnectError:
        pytest.fail(f"Could not connect to {PC2_URL}. Ensure PC2 is online.")

def test_chat_llama_response():
    """Verify llama3.1:8b handles chat reasoning."""
    payload = {
        "model": "llama3.1:8b",
        "messages": [{"role": "user", "content": "respond with exactly one word: pong"}],
        "stream": False,
        "keep_alive": "24h"
    }
    
    t0 = time.time()
    r = httpx.post(f"{PC2_URL}/api/chat", json=payload, timeout=30.0)
    elapsed = time.time() - t0
    
    assert r.status_code == 200, f"Chat failed: {r.text}"
    
    msg = r.json().get("message", {}).get("content", "").strip().lower()
    print(f"\n[CHAT] Latency: {elapsed:.2f}s, Response: {msg}")
    
    assert "pong" in msg, f"Expected 'pong' in response, got '{msg}'"

def test_embed_snowflake():
    """Verify snowflake-arctic-embed2 produces 1024-dim dense vectors."""
    payload = {
        "model": "snowflake-arctic-embed2:latest",
        "input": "test embedding probe",
        "keep_alive": "24h"
    }
    
    t0 = time.time()
    r = httpx.post(f"{PC2_URL}/api/embed", json=payload, timeout=120.0)
    elapsed = time.time() - t0
    
    assert r.status_code == 200, f"Embed failed: {r.text}"
    
    embeddings: List[List[float]] = r.json().get("embeddings", [])
    assert len(embeddings) == 1, "Expected exactly 1 embedding returned"
    
    dim = len(embeddings[0])
    print(f"\n[EMBED] Latency: {elapsed:.2f}s, Dimension: {dim}")
    
    assert dim == 1024, f"Expected 1024 dimensions, got {dim}"

def test_embed_batch_performance():
    """Verify batch embedding performance on PC2 GPU."""
    texts = [f"sample chunk text {i} for batching" for i in range(16)]
    payload = {
        "model": "snowflake-arctic-embed2:latest",
        "input": texts,
        "keep_alive": "24h"
    }
    
    t0 = time.time()
    r = httpx.post(f"{PC2_URL}/api/embed", json=payload, timeout=30.0)
    elapsed = time.time() - t0
    
    assert r.status_code == 200, f"Batch embed failed: {r.text}"
    
    embeddings = r.json().get("embeddings", [])
    print(f"\n[BATCH EMBED] 16 chunks in {elapsed:.2f}s")
    
    assert len(embeddings) == 16, f"Expected 16 embeddings, got {len(embeddings)}"
    assert len(embeddings[0]) == 1024
