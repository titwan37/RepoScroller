"""Embedding adapter for dense vector representations using snowflake-arctic-embed and Ollama."""

import math
import hashlib
from typing import List, Optional, Union
import httpx
from reposcroller.config import settings


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
                 dimension: int = 1024):
        self.provider = provider or settings.EMBEDDING_PROVIDER
        self.model_name = model_name or settings.OLLAMA_EMBEDDING_MODEL
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.dimension = dimension

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
        """Embed a single string."""
        if not text or not text.strip():
            return [0.0] * self.dimension

        if self.provider in ["auto", "ollama"]:
            try:
                # 1. Try modern Ollama /api/embed endpoint
                resp = httpx.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model_name, "input": text},
                    timeout=5.0
                )
                if resp.status_code == 200:
                    data = resp.json()
                    embeddings = data.get("embeddings", [])
                    if embeddings and isinstance(embeddings[0], list):
                        return embeddings[0]

                # 2. Try legacy Ollama /api/embeddings endpoint
                resp_legacy = httpx.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model_name, "prompt": text},
                    timeout=5.0
                )
                if resp_legacy.status_code == 200:
                    data = resp_legacy.json()
                    emb = data.get("embedding", [])
                    if emb:
                        return emb
            except Exception:
                pass

        return self._fallback_pseudo_embedding(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of strings in batch."""
        if not texts:
            return []

        if self.provider in ["auto", "ollama"]:
            try:
                resp = httpx.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model_name, "input": texts},
                    timeout=10.0
                )
                if resp.status_code == 200:
                    data = resp.json()
                    embeddings = data.get("embeddings", [])
                    if embeddings and len(embeddings) == len(texts):
                        return embeddings
            except Exception:
                pass

        return [self.embed_text(t) for t in texts]
