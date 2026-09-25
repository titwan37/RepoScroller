"""Embedding adapter for dense vector representations using snowflake-arctic-embed and Ollama."""

import math
import hashlib
import logging
from typing import List, Optional, Union
import httpx
from reposcroller.config import settings

logger = logging.getLogger("reposcroller.ai.embeddings")

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two normalized or raw floating point vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


class EmbeddingAdapter:
    """Generates dense vector embeddings using Ollama (e.g. snowflake-arctic-embed:latest) or fallback."""

    def __init__(self,
                 provider: Optional[str] = None,
                 model_name: Optional[str] = None,
                 base_url: Optional[str] = None,
                 dimension: int = 1024,
                 timeout: Optional[float] = None,
                 keep_alive: Optional[str] = None,
                 sub_batch_size: Optional[int] = None):
        self.provider = provider or settings.EMBEDDING_PROVIDER
        self.model_name = model_name or settings.OLLAMA_EMBEDDING_MODEL
        self.base_url = (base_url or settings.embed_url).rstrip("/")
        self.dimension = dimension
        self.timeout = timeout if timeout is not None else getattr(settings, "OLLAMA_TIMEOUT", 60.0)
        self.keep_alive = keep_alive or getattr(settings, "OLLAMA_KEEP_ALIVE", "24h")
        self.sub_batch_size = sub_batch_size or getattr(settings, "OLLAMA_SUB_BATCH_SIZE", 32)
        
        # Reuse persistent client connection pool with reasonable timeouts
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.timeout, connect=5.0, read=self.timeout, write=10.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )

    def _fallback_pseudo_embedding(self, text: str) -> List[float]:
        """Deterministic, normalized pseudo-embedding based on character n-grams for offline/fallback."""
        vec = [0.0] * self.dimension
        if not text:
            return vec

        words = text.lower().split()
        for i, w in enumerate(words):
            h = int(hashlib.sha256(w.encode("utf-8")).hexdigest()[:8], 16)
            idx = h % self.dimension
            vec[idx] += 1.0 / (1.0 + (i * 0.05))

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def embed_text(self, text: str) -> List[float]:
        """Embed a single string with keep_alive and extended timeout."""
        if not text or not text.strip():
            return [0.0] * self.dimension

        if self.provider in ["auto", "ollama"]:
            t0 = time.time()
            try:
                # 1. Try modern Ollama /api/embed endpoint
                resp = self._client.post(
                    f"{self.base_url}/api/embed",
                    json={
                        "model": self.model_name,
                        "input": text,
                        "keep_alive": self.keep_alive
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    embeddings = data.get("embeddings", [])
                    if embeddings and isinstance(embeddings[0], list):
                        elapsed_ms = (time.time() - t0) * 1000
                        from reposcroller.ai.telemetry import workload_telemetry
                        workload_telemetry.record_embedding(chunk_count=1, latency_ms=elapsed_ms, success=True)
                        return embeddings[0]

                # 2. Try legacy Ollama /api/embeddings endpoint
                resp_legacy = self._client.post(
                    f"{self.base_url}/api/embeddings",
                    json={
                        "model": self.model_name,
                        "prompt": text,
                        "keep_alive": self.keep_alive
                    }
                )
                if resp_legacy.status_code == 200:
                    data = resp_legacy.json()
                    emb = data.get("embedding", [])
                    if emb:
                        elapsed_ms = (time.time() - t0) * 1000
                        from reposcroller.ai.telemetry import workload_telemetry
                        workload_telemetry.record_embedding(chunk_count=1, latency_ms=elapsed_ms, success=True)
                        return emb
                else:
                    logger.warning(f"Ollama returned HTTP {resp_legacy.status_code} for model '{self.model_name}' at {self.base_url}")
            except Exception as exc:
                elapsed_ms = (time.time() - t0) * 1000
                from reposcroller.ai.telemetry import workload_telemetry
                workload_telemetry.record_embedding(chunk_count=1, latency_ms=elapsed_ms, success=False)
                logger.warning(f"Ollama embedding request failed at {self.base_url} ({exc}). Using pseudo-embedding fallback.")

        return self._fallback_pseudo_embedding(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of strings using sliced sub-batching to prevent Ollama timeouts."""
        if not texts:
            return []

        if self.provider in ["auto", "ollama"]:
            results: List[List[float]] = []
            chunk_step = max(1, self.sub_batch_size)
            batch_t0 = time.time()

            for i in range(0, len(texts), chunk_step):
                sub_slice = texts[i:i + chunk_step]
                t_slice = time.time()
                try:
                    resp = self._client.post(
                        f"{self.base_url}/api/embed",
                        json={
                            "model": self.model_name,
                            "input": sub_slice,
                            "keep_alive": self.keep_alive
                        }
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        embeddings = data.get("embeddings", [])
                        if embeddings and len(embeddings) == len(sub_slice):
                            elapsed_slice = (time.time() - t_slice) * 1000
                            from reposcroller.ai.telemetry import workload_telemetry
                            workload_telemetry.record_embedding(chunk_count=len(sub_slice), latency_ms=elapsed_slice, success=True)
                            results.extend(embeddings)
                            continue
                    
                    # If endpoint returned non-200 or incomplete, fall back for this sub_slice
                    logger.warning(f"Ollama sub-batch embed returned HTTP {resp.status_code}. Processing sub-slice sequentially.")
                    results.extend([self.embed_text(t) for t in sub_slice])
                except Exception as exc:
                    elapsed_slice = (time.time() - t_slice) * 1000
                    from reposcroller.ai.telemetry import workload_telemetry
                    workload_telemetry.record_embedding(chunk_count=len(sub_slice), latency_ms=elapsed_slice, success=False)
                    logger.warning(f"Ollama sub-batch embed failed for slice [{i}:{i+len(sub_slice)}] ({exc}). Processing sequentially.")
                    results.extend([self.embed_text(t) for t in sub_slice])

            if len(results) == len(texts):
                return results

        return [self.embed_text(t) for t in texts]


