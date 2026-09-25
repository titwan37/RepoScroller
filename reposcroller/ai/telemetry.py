"""Workload telemetry and dual-node monitoring (Localhost CPU/Chat vs Remote CUDA Embeddings)."""

import time
import logging
import threading
from typing import Dict, Any, List, Optional
import httpx
from reposcroller.config import settings

logger = logging.getLogger("reposcroller.ai.telemetry")


class WorkloadTelemetry:
    """Thread-safe telemetry tracker for dual-node split workload execution."""

    def __init__(self):
        self.lock = threading.RLock()
        
        # Chat Telemetry (PC1 Localhost / LLM)
        self.chat_requests = 0
        self.chat_total_latency_ms = 0.0
        self.chat_last_latency_ms = 0.0
        self.chat_errors = 0
        self.chat_last_timestamp = None

        # Embedding Telemetry (PC2 Remote CUDA GPU)
        self.embed_requests = 0
        self.embed_total_chunks = 0
        self.embed_total_latency_ms = 0.0
        self.embed_last_latency_ms = 0.0
        self.embed_errors = 0
        self.embed_last_timestamp = None

        # Health / Probe Cache (5s TTL)
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

    def record_embedding(self, chunk_count: int, latency_ms: float, success: bool = True):
        """Record an api/embed or vector tensor generation event."""
        with self.lock:
            self.embed_requests += 1
            if success:
                self.embed_total_chunks += chunk_count
                self.embed_total_latency_ms += latency_ms
                self.embed_last_latency_ms = round(latency_ms, 2)
            else:
                self.embed_errors += 1
            self.embed_last_timestamp = time.strftime("%H:%M:%S")

    def get_node_probes(self, force: bool = False) -> Dict[str, Any]:
        """Probe both PC1 (Localhost) and PC2 (Remote CUDA) endpoints with caching."""
        now = time.time()
        if not force and (now - self._cache_time < 4.0) and self._cached_nodes:
            return self._cached_nodes

        chat_url = settings.chat_url
        embed_url = settings.embed_url

        local_node = self._probe_single_node(chat_url, expected_role="chat")
        cuda_node = self._probe_single_node(embed_url, expected_role="embed")

        with self.lock:
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
                    "stats": {
                        "requests": self.embed_requests,
                        "chunks_embedded": self.embed_total_chunks,
                        "last_latency_ms": self.embed_last_latency_ms,
                        "avg_latency_ms": avg_embed_latency,
                        "errors": self.embed_errors,
                        "last_active": self.embed_last_timestamp or "idle"
                    }
                }
            }
            self._cached_nodes = result
            self._cache_time = now
            return result

    def _probe_single_node(self, base_url: str, expected_role: str) -> Dict[str, Any]:
        """Test reachability and list running models on a single Ollama instance."""
        t0 = time.time()
        try:
            with httpx.Client(timeout=1.5) as client:
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

        # Try tags fallback
        try:
            with httpx.Client(timeout=1.5) as client:
                r2 = client.get(f"{base_url.rstrip('/')}/api/tags")
                elapsed_ms = round((time.time() - t0) * 1000, 2)
                if r2.status_code == 200:
                    return {
                        "online": True,
                        "ping_ms": elapsed_ms,
                        "models_loaded": ["(idle / on-demand)"]
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
