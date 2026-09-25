"""Embedding adapter for dense vector representations using snowflake-arctic-embed and Ollama."""

import math
import hashlib
import time
import logging
from typing import List, Optional, Union, Tuple
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
    """Generates dense vector embeddings using a 3-tier resilient hierarchy:
       - Tier 1 (Primary): Remote CUDA GPU Node (e.g. snowflake-arctic-embed2:latest on PC2 RTX 3060) [GREEN]
       - Tier 2 (Secondary Fallback): Localhost CPU Ollama (e.g. snowflake-arctic-embed:latest on PC1) [ORANGE]
       - Tier 3 (Tertiary Fallback): Deterministic Offline Pseudo-Embedding [RED]
    """

    def __init__(self,
                 provider: Optional[str] = None,
                 model_name: Optional[str] = None,
                 base_url: Optional[str] = None,
                 local_url: Optional[str] = None,
                 local_model_name: Optional[str] = None,
                 dimension: int = 1024,
                 timeout: Optional[float] = None,
                 keep_alive: Optional[str] = None,
                 sub_batch_size: Optional[int] = None):
        self.provider = provider or settings.EMBEDDING_PROVIDER
        
        # Tier 1 (Remote CUDA GPU Node)
        self.base_url = (base_url or settings.embed_url).rstrip("/")
        self.model_name = model_name or settings.OLLAMA_EMBEDDING_MODEL

        # Tier 2 (Local CPU Fallback Node)
        self.local_url = (local_url or settings.local_embed_url).rstrip("/")
        self.local_model_name = local_model_name or settings.OLLAMA_LOCAL_EMBEDDING_MODEL

        self.dimension = dimension
        self.timeout = timeout if timeout is not None else float(getattr(settings, "OLLAMA_TIMEOUT", 300.0))
        self.keep_alive = keep_alive or getattr(settings, "OLLAMA_KEEP_ALIVE", "24h")
        self.sub_batch_size = sub_batch_size or int(getattr(settings, "OLLAMA_SUB_BATCH_SIZE", 16))
        
        # Persistent client connection pool with generous connect & read timeouts (high patience for CPU/GPU)
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.timeout, connect=15.0, read=self.timeout, write=30.0),
            limits=httpx.Limits(max_keepalive_connections=8, max_connections=16)
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

    def _try_single_ollama(self, url: str, model: str, text: str) -> Tuple[Optional[List[float]], Optional[str]]:
        """Attempt single text embedding on a specific Ollama node, returning (embedding, error_reason)."""
        last_err = None
        # 1. Try modern Ollama /api/embed
        try:
            resp = self._client.post(
                f"{url}/api/embed",
                json={
                    "model": model,
                    "input": text,
                    "keep_alive": self.keep_alive
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                embeddings = data.get("embeddings", [])
                if embeddings and isinstance(embeddings[0], list):
                    return embeddings[0], None
            else:
                last_err = f"HTTP {resp.status_code}: {resp.text[:120]}"
        except httpx.TimeoutException:
            last_err = f"Request timed out (>{self.timeout}s)"
        except httpx.ConnectError:
            last_err = "Connection refused (host offline or port closed)"
        except Exception as exc:
            last_err = str(exc)

        # 2. Try legacy Ollama /api/embeddings
        try:
            resp_legacy = self._client.post(
                f"{url}/api/embeddings",
                json={
                    "model": model,
                    "prompt": text,
                    "keep_alive": self.keep_alive
                }
            )
            if resp_legacy.status_code == 200:
                data = resp_legacy.json()
                emb = data.get("embedding", [])
                if emb:
                    return emb, None
            else:
                last_err = f"Legacy HTTP {resp_legacy.status_code}: {resp_legacy.text[:120]}"
        except httpx.TimeoutException:
            last_err = f"Request timed out (>{self.timeout}s)"
        except Exception as exc:
            last_err = str(exc)

        return None, last_err

    def _try_batch_ollama(self, url: str, model: str, texts: List[str]) -> Tuple[Optional[List[List[float]]], int, Optional[str]]:
        """Attempt batch text embedding on a specific Ollama node, returning (embeddings, tokens, error_reason)."""
        try:
            resp = self._client.post(
                f"{url}/api/embed",
                json={
                    "model": model,
                    "input": texts,
                    "keep_alive": self.keep_alive
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                embeddings = data.get("embeddings", [])
                tokens = data.get("prompt_eval_count")
                if not tokens:
                    tokens = sum(len(t.split()) for t in texts)
                if embeddings and len(embeddings) == len(texts):
                    return embeddings, int(tokens), None
                return None, 0, f"Incomplete batch returned: got {len(embeddings or [])}/{len(texts)} embeddings"
            return None, 0, f"HTTP {resp.status_code}: {resp.text[:120]}"
        except httpx.TimeoutException:
            return None, 0, f"Request timed out (>{self.timeout}s)"
        except httpx.ConnectError:
            return None, 0, f"Connection refused to {url}"
        except Exception as exc:
            return None, 0, str(exc)

    def embed_text(self, text: str) -> List[float]:
        """Embed a single string through the 3-tier resilient embedding hierarchy."""
        if not text or not text.strip():
            return [0.0] * self.dimension

        if self.provider in ["auto", "ollama"]:
            from reposcroller.ai.telemetry import workload_telemetry

            # --- TIER 1: Remote CUDA GPU Node (PC2) ---
            t0 = time.time()
            emb, err_pc2 = self._try_single_ollama(self.base_url, self.model_name, text)
            if emb:
                elapsed_ms = (time.time() - t0) * 1000
                workload_telemetry.record_embedding(
                    chunk_count=1,
                    latency_ms=elapsed_ms,
                    success=True,
                    tier="cuda",
                    target_url=self.base_url,
                    model=self.model_name,
                    tokens=len(text.split())
                )
                return emb

            logger.warning(f"Tier 1 (Remote CUDA Node at {self.base_url}) failed: {err_pc2}. Trying Tier 2 Local CPU Fallback ({self.local_url})...")

            # --- TIER 2: Localhost CPU Fallback Node (PC1) ---
            t1 = time.time()
            emb_local, err_pc1 = self._try_single_ollama(self.local_url, self.local_model_name, text)
            if not emb_local and self.model_name != self.local_model_name:
                # Also check if the primary model name happens to be installed locally
                emb_local, err_pc1 = self._try_single_ollama(self.local_url, self.model_name, text)

            if emb_local:
                elapsed_ms = (time.time() - t1) * 1000
                workload_telemetry.record_embedding(
                    chunk_count=1,
                    latency_ms=elapsed_ms,
                    success=True,
                    tier="local",
                    target_url=self.local_url,
                    model=self.local_model_name,
                    error_msg=f"PC2 unavailable ({err_pc2}). Active on PC1 Localhost.",
                    tokens=len(text.split())
                )
                return emb_local

            logger.warning(f"Tier 2 (Local CPU Node at {self.local_url}) failed: {err_pc1}. Falling back to Tier 3 Pseudo-Embedding...")

            # --- TIER 3: Deterministic Offline Pseudo-Embedding Fallback ---
            elapsed_ms = (time.time() - t0) * 1000
            workload_telemetry.record_embedding(
                chunk_count=1,
                latency_ms=elapsed_ms,
                success=False,
                tier="fallback",
                target_url="offline",
                model="pseudo-sha256",
                error_msg=f"Tier 1 PC2 failed ({err_pc2}) & Tier 2 PC1 failed ({err_pc1})"
            )

        return self._fallback_pseudo_embedding(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of strings through the 3-tier resilient hierarchy using sliced sub-batching."""
        if not texts:
            return []

        if self.provider in ["auto", "ollama"]:
            from reposcroller.ai.telemetry import workload_telemetry
            chunk_step = max(1, self.sub_batch_size)

            # --- TIER 1: Remote CUDA GPU Node (PC2) ---
            t0 = time.time()
            tier1_results: List[List[float]] = []
            tier1_tokens = 0
            tier1_success = True
            err_pc2 = None

            for i in range(0, len(texts), chunk_step):
                sub_slice = texts[i:i + chunk_step]
                emb_slice, tokens, slice_err = self._try_batch_ollama(self.base_url, self.model_name, sub_slice)
                if emb_slice:
                    tier1_results.extend(emb_slice)
                    tier1_tokens += tokens
                else:
                    tier1_success = False
                    err_pc2 = f"Slice [{i}:{i+len(sub_slice)}] on {self.base_url} failed ({slice_err})"
                    break

            if tier1_success and len(tier1_results) == len(texts):
                elapsed_ms = (time.time() - t0) * 1000
                workload_telemetry.record_embedding(
                    chunk_count=len(texts),
                    latency_ms=elapsed_ms,
                    success=True,
                    tier="cuda",
                    target_url=self.base_url,
                    model=self.model_name,
                    tokens=tier1_tokens
                )
                return tier1_results

            logger.warning(f"Tier 1 (Remote CUDA Node at {self.base_url}) failed: {err_pc2}. Attempting Tier 2 Localhost CPU Fallback ({self.local_url})...")

            # --- TIER 2: Localhost CPU Fallback Node (PC1) ---
            t1 = time.time()
            tier2_results: List[List[float]] = []
            tier2_tokens = 0
            tier2_success = True
            err_pc1 = None
            active_local_model = self.local_model_name

            for i in range(0, len(texts), chunk_step):
                sub_slice = texts[i:i + chunk_step]
                emb_slice, tokens, slice_err = self._try_batch_ollama(self.local_url, self.local_model_name, sub_slice)
                if not emb_slice and self.model_name != self.local_model_name:
                    emb_slice, tokens, slice_err = self._try_batch_ollama(self.local_url, self.model_name, sub_slice)
                    if emb_slice:
                        active_local_model = self.model_name

                if emb_slice:
                    tier2_results.extend(emb_slice)
                    tier2_tokens += tokens
                else:
                    tier2_success = False
                    err_pc1 = f"Local slice [{i}:{i+len(sub_slice)}] on {self.local_url} failed ({slice_err})"
                    break

            if tier2_success and len(tier2_results) == len(texts):
                elapsed_ms = (time.time() - t1) * 1000
                workload_telemetry.record_embedding(
                    chunk_count=len(texts),
                    latency_ms=elapsed_ms,
                    success=True,
                    tier="local",
                    target_url=self.local_url,
                    model=active_local_model,
                    error_msg=f"PC2 unavailable ({err_pc2}). Running on Localhost CPU.",
                    tokens=tier2_tokens
                )
                logger.info(f"⚡ Successfully embedded {len(texts)} chunks using Tier 2 Localhost CPU Fallback ({active_local_model}) at {self.local_url}.")
                return tier2_results

            logger.error(f"Tier 2 (Localhost CPU at {self.local_url}) failed: {err_pc1}. Degrading to Tier 3 Offline Pseudo-Embedding...")

            # --- TIER 3: Deterministic Offline Pseudo-Embedding Fallback ---
            elapsed_ms = (time.time() - t0) * 1000
            workload_telemetry.record_embedding(
                chunk_count=len(texts),
                latency_ms=elapsed_ms,
                success=False,
                tier="fallback",
                target_url="offline",
                model="pseudo-sha256",
                error_msg=f"Tier 1 failed ({err_pc2}) & Tier 2 failed ({err_pc1})"
            )

        return [self._fallback_pseudo_embedding(t) for t in texts]



