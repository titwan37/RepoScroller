"""Diagnostic test and benchmark for PC2 CUDA GPU Ollama node."""

import time
import httpx
import pytest
from reposcroller.config import settings


def test_pc2_lan_connectivity():
    """Verify PC2 Ollama HTTP endpoint is reachable over LAN."""
    t0 = time.time()
    resp = httpx.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=5.0)
    latency_ms = round((time.time() - t0) * 1000, 2)
    assert resp.status_code == 200
    models = [m["name"] for m in resp.json().get("models", [])]
    print(f"\n[PC2 LAN] Connected in {latency_ms}ms. Available models: {models}")
    assert any("snowflake-arctic-embed" in m for m in models)


def test_pc2_embedding_inference():
    """Benchmark snowflake-arctic-embed embedding inference on PC2 CUDA GPU."""
    model = settings.OLLAMA_EMBEDDING_MODEL
    texts = [
        "Contract between Swisscom AG and John Doe in Zurich.",
        "Employment agreement governing intellectual property assignment and non-compete covenants."
    ]
    t0 = time.time()
    resp = httpx.post(
        f"{settings.OLLAMA_BASE_URL}/api/embed",
        json={"model": model, "input": texts, "keep_alive": "24h"},
        timeout=60.0
    )
    duration_ms = round((time.time() - t0) * 1000, 2)
    assert resp.status_code == 200
    embeddings = resp.json().get("embeddings", [])
    assert len(embeddings) == 2
    dim = len(embeddings[0])
    print(f"\n[PC2 CUDA Embedding] Model: {model} -> {len(embeddings)} vectors ({dim}-dim) generated in {duration_ms}ms")


if __name__ == "__main__":
    print("=== Running PC2 LAN GPU Benchmarks ===")
    test_pc2_lan_connectivity()
    test_pc2_embedding_inference()