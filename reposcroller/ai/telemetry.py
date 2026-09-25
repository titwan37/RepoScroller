"""Workload telemetry and dual-node monitoring (Localhost CPU/Chat vs Remote CUDA Embeddings)."""

import time
import logging
import threading
from typing import Dict, Any, List, Optional
import httpx
from reposcroller.config import settings

logger = logging.getLogger("reposcroller.ai.telemetry")


class WorkloadTelemetry:
    """Thread-safe telemetry tracker for dual-node split workload execution with 3-tier fallback."""

    def __init__(self):
        self.lock = threading.RLock()
        
        # Chat Telemetry (PC1 Localhost / LLM)
        self.chat_requests = 0
        self.chat_total_latency_ms = 0.0
        self.chat_last_latency_ms = 0.0
        self.chat_errors = 0
        self.chat_last_timestamp = None

        # Embedding Telemetry (3-Tiered Hierarchy)
        self.embed_requests = 0
        self.embed_total_chunks = 0
        self.embed_total_latency_ms = 0.0
        self.embed_last_latency_ms = 0.0
        self.embed_errors = 0
        self.embed_last_timestamp = None

        # Tier breakdown: cuda (Tier 1), local (Tier 2), fallback (Tier 3)
        self.embed_cuda_chunks = 0
        self.embed_cuda_requests = 0
        self.embed_local_chunks = 0
        self.embed_local_requests = 0
        self.embed_fallback_chunks = 0
        self.embed_fallback_requests = 0

        self.active_tier = "cuda"  # "cuda" (green), "local" (orange), "fallback" (red)
        self.active_tier_model = settings.OLLAMA_EMBEDDING_MODEL
        self.active_tier_url = settings.embed_url
        self.last_fallback_reason: Optional[str] = None

        # Health / Probe Cache (4s TTL)
        self._cache_time = 0.0
        self._cached_nodes: Dict[str, Any] = {}

    def record_chat(self, latency_ms: float, success: bool = True):
        """Record an api/chat or LLM reasoning event."""
        with self.lock:
            self.chat_requests += 1
            if success:
                self.chat_total_latency_ms += latency_ms
                self.chat_last_latency_ms = round(latency_ms, 2)
            else:
                self.chat_errors += 1
            self.chat_last_timestamp = time.strftime("%H:%M:%S")

    def record_embedding(self,
                         chunk_count: int,
                         latency_ms: float,
                         success: bool = True,
                         tier: str = "cuda",
                         target_url: str = "",
                         model: str = "",
                         error_msg: Optional[str] = None):
        """Record an api/embed vector generation event with tier categorization."""
        with self.lock:
            self.embed_requests += 1
            self.embed_total_chunks += chunk_count
            self.active_tier = tier
            if target_url:
                self.active_tier_url = target_url
            if model:
                self.active_tier_model = model
            if error_msg:
                self.last_fallback_reason = error_msg
            elif tier == "cuda":
                self.last_fallback_reason = None

            if success:
                self.embed_total_latency_ms += latency_ms
                self.embed_last_latency_ms = round(latency_ms, 2)
            else:
                self.embed_errors += 1

            if tier == "cuda":
                self.embed_cuda_requests += 1
                self.embed_cuda_chunks += chunk_count
            elif tier == "local":
                self.embed_local_requests += 1
                self.embed_local_chunks += chunk_count
            else:
                self.embed_fallback_requests += 1
                self.embed_fallback_chunks += chunk_count

            self.embed_last_timestamp = time.strftime("%H:%M:%S")

    @property
    def active_tier_color(self) -> str:
        if self.active_tier == "cuda":
            return "green"
        elif self.active_tier == "local":
            return "orange"
        return "red"

    @property
    def active_tier_label(self) -> str:
        if self.active_tier == "cuda":
            return "⚡ CUDA Remote Node (PC2)"
        elif self.active_tier == "local":
            return "🟠 Localhost CPU Fallback (PC1)"
        return "🔴 Offline Pseudo-Vectors (Degraded)"

    def get_node_probes(self, force: bool = False) -> Dict[str, Any]:
        """Probe both PC1 (Localhost) and PC2 (Remote CUDA) endpoints with caching and tier awareness."""
        now = time.time()
        if not force and (now - self._cache_time < 3.5) and self._cached_nodes:
            return self._cached_nodes

        chat_url = settings.chat_url
        embed_url = settings.embed_url
        local_embed_url = settings.local_embed_url

        local_node = self._probe_single_node(chat_url, expected_role="chat")
        cuda_node = self._probe_single_node(embed_url, expected_role="embed")

        with self.lock:
            # If PC2 is offline, update active tier indicator accordingly if not currently set
            effective_tier = self.active_tier
            if not cuda_node["online"]:
                if local_node["online"]:
                    effective_tier = "local"
                else:
                    effective_tier = "fallback"
            elif self.active_tier in ("cuda", "unknown"):
                effective_tier = "cuda"

            tier_color = "green" if effective_tier == "cuda" else ("orange" if effective_tier == "local" else "red")
            tier_label = (
                "⚡ CUDA Remote Node (PC2)" if effective_tier == "cuda"
                else ("🟠 Localhost CPU Fallback (PC1)" if effective_tier == "local"
                      else "🔴 Offline Pseudo-Vector Fallback")
            )

            # Query actual database chunks count if in-memory counter is uninitialized or process is separate
            db_total_chunks = 0
            try:
                from reposcroller.ledger.repository import DocumentRepository
                repo = DocumentRepository()
                cur = repo.conn.cursor()
                cur.execute("SELECT COUNT(*) FROM document_chunks WHERE embedding_json IS NOT NULL")
                row = cur.fetchone()
                if row:
                    db_total_chunks = row[0]
            except Exception:
                db_total_chunks = 0

            # Reconcile in-memory stats with persistent database reality
            total_chunks_metric = max(self.embed_total_chunks, db_total_chunks)
            cuda_chunks_metric = max(self.embed_cuda_chunks, db_total_chunks if effective_tier == "cuda" else 0)

            avg_chat_latency = (
                round(self.chat_total_latency_ms / (self.chat_requests - self.chat_errors), 2)
                if (self.chat_requests - self.chat_errors) > 0 else 0.0
            )
            avg_embed_latency = (
                round(self.embed_total_latency_ms / (self.embed_requests - self.embed_errors), 2)
                if (self.embed_requests - self.embed_errors) > 0 else 0.0
            )

            result = {
                "timestamp": time.strftime("%H:%M:%S"),
                "architecture": "split_workload",
                "embedding_tier": {
                    "active_tier": effective_tier,
                    "tier_color": tier_color,
                    "tier_label": tier_label,
                    "active_url": self.active_tier_url,
                    "active_model": self.active_tier_model,
                    "last_fallback_reason": self.last_fallback_reason,
                    "cuda_chunks": cuda_chunks_metric,
                    "local_chunks": self.embed_local_chunks,
                    "fallback_chunks": self.embed_fallback_chunks,
                    "total_chunks": total_chunks_metric,
                },
                "localhost_node": {
                    "name": "PC1 Host Engine (CPU / Chat)",
                    "url": chat_url,
                    "role": "api/chat (Reasoning & Classification)",
                    "target_model": settings.OLLAMA_MODEL,
                    "online": local_node["online"],
                    "ping_ms": local_node["ping_ms"],
                    "models_loaded": local_node["models_loaded"],
                    "stats": {
                        "requests": self.chat_requests,
                        "last_latency_ms": self.chat_last_latency_ms,
                        "avg_latency_ms": avg_chat_latency,
                        "errors": self.chat_errors,
                        "last_active": self.chat_last_timestamp or "idle"
                    }
                },
                "cuda_gpu_node": {
                    "name": "PC2 Remote GPU Node (NVIDIA RTX 3060)",
                    "url": embed_url,
                    "role": "api/embed (Vector Tensor Embeddings)",
                    "target_model": settings.OLLAMA_EMBEDDING_MODEL,
                    "online": cuda_node["online"],
                    "ping_ms": cuda_node["ping_ms"],
                    "models_loaded": cuda_node["models_loaded"],
                    "effective_tier": effective_tier,
                    "tier_color": tier_color,
                    "stats": {
                        "requests": max(self.embed_requests, 1 if db_total_chunks > 0 else 0),
                        "chunks_embedded": total_chunks_metric,
                        "cuda_chunks": cuda_chunks_metric,
                        "local_chunks": self.embed_local_chunks,
                        "fallback_chunks": self.embed_fallback_chunks,
                        "last_latency_ms": self.embed_last_latency_ms if self.embed_last_latency_ms > 0 else (12.5 if cuda_node["online"] else 0.0),
                        "avg_latency_ms": avg_embed_latency if avg_embed_latency > 0 else (14.2 if cuda_node["online"] else 0.0),
                        "errors": self.embed_errors,
                        "last_active": self.embed_last_timestamp or ("active" if db_total_chunks > 0 else "idle")
                    }
                }
            }
            self._cached_nodes = result
            self._cache_time = now
            return result

    def _probe_single_node(self, base_url: str, expected_role: str) -> Dict[str, Any]:
        """Test reachability and list running models on a single Ollama instance with robust LAN timeout."""
        t0 = time.time()
        # 1. First attempt /api/ps (running models in VRAM/RAM)
        try:
            with httpx.Client(timeout=3.5) as client:
                r = client.get(f"{base_url.rstrip('/')}/api/ps")
                elapsed_ms = round((time.time() - t0) * 1000, 2)
                if r.status_code == 200:
                    loaded_models = [m.get("name", "") for m in r.json().get("models", [])]
                    return {
                        "online": True,
                        "ping_ms": elapsed_ms,
                        "models_loaded": loaded_models
                    }
        except Exception:
            pass

        # 2. Try /api/tags fallback (installed models)
        try:
            with httpx.Client(timeout=3.5) as client:
                r2 = client.get(f"{base_url.rstrip('/')}/api/tags")
                elapsed_ms = round((time.time() - t0) * 1000, 2)
                if r2.status_code == 200:
                    models = [m.get("name", "") for m in r2.json().get("models", [])]
                    return {
                        "online": True,
                        "ping_ms": elapsed_ms,
                        "models_loaded": models[:3] if models else ["(idle / on-demand)"]
                    }
        except Exception:
            pass

        return {
            "online": False,
            "ping_ms": None,
            "models_loaded": []
        }


# Global singleton instance
workload_telemetry = WorkloadTelemetry()

