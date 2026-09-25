"""Qdrant Vector Store Plugin for Enterprise HNSW Indexing in RepoScroller.

Provides high-scale sub-millisecond dense vector retrieval across millions of
document chunks using an optional Qdrant vector database instance or cluster.
Falls back safely and cleanly when Qdrant or qdrant-client is absent.
"""

import uuid
import logging
from typing import List, Dict, Any, Optional
from reposcroller.config import settings

logger = logging.getLogger("reposcroller.qdrant")

# Namespace UUID for deterministic chunk point IDs
REPO_NAMESPACE_UUID = uuid.UUID("a7e6e58b-9441-4567-b5bf-73c15372fa91")


class QdrantVectorStorePlugin:
    """Plugin interface for Qdrant Vector Database."""

    def __init__(self,
                 url: Optional[str] = None,
                 api_key: Optional[str] = None,
                 collection_name: Optional[str] = None,
                 prefer_grpc: Optional[bool] = None):
        self.url = url or settings.QDRANT_URL or "http://localhost:6333"
        self.api_key = api_key or settings.QDRANT_API_KEY
        self.collection_name = collection_name or settings.QDRANT_COLLECTION or "reposcroller_chunks"
        self.prefer_grpc = prefer_grpc if prefer_grpc is not None else settings.QDRANT_PREFER_GRPC
        
        self._client = None
        self._models = None
        self._available = False
        self._initialized_collections = set()

        self._init_client()

    def _init_client(self) -> None:
        """Lazily imports and establishes connection to Qdrant client."""
        if settings.VECTOR_STORE_TYPE.lower() != "qdrant":
            self._available = False
            return

        try:
            from qdrant_client import QdrantClient, models  # type: ignore[import-not-found,import-untyped]
            self._models = models
            self._client = QdrantClient(
                url=self.url,
                api_key=self.api_key,
                prefer_grpc=self.prefer_grpc,
                timeout=1.0,
                check_compatibility=False
            )
            # Ping / test connection
            self._client.get_collections()
            self._available = True
            logger.info("Qdrant client initialized and connected to %s", self.url)
        except ImportError:
            logger.debug("qdrant-client is not installed. Qdrant plugin disabled.")
            self._available = False
        except Exception as exc:
            logger.warning("Could not connect to Qdrant at %s: %s. Operating in offline/fallback mode.", self.url, exc)
            self._available = False

    @property
    def is_available(self) -> bool:
        """Returns True if Qdrant client is connected and active."""
        return self._available and self._client is not None

    def ensure_collection(self, vector_size: int = 1024) -> bool:
        """Ensures the target Qdrant collection exists with proper Cosine vector configuration."""
        if not self.is_available:
            return False

        if self.collection_name in self._initialized_collections:
            return True

        try:
            collections = self._client.get_collections().collections
            exists = any(c.name == self.collection_name for c in collections)
            if not exists:
                self._client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=self._models.VectorParams(
                        size=vector_size,
                        distance=self._models.Distance.COSINE
                    )
                )
                logger.info("Created Qdrant collection '%s' with vector size %d", self.collection_name, vector_size)
            self._initialized_collections.add(self.collection_name)
            return True
        except Exception as exc:
            logger.error("Failed to ensure Qdrant collection '%s': %s", self.collection_name, exc)
            return False

    def upsert_chunks(self,
                      sha256_hash: str,
                      chunks: List[Dict[str, Any]],
                      doc_metadata: Optional[Dict[str, Any]] = None) -> int:
        """Upserts a batch of document chunks with vectors into Qdrant."""
        if not self.is_available or not chunks:
            return 0

        valid_chunks = [c for c in chunks if c.get("embedding")]
        if not valid_chunks:
            return 0

        vector_size = len(valid_chunks[0]["embedding"])
        if not self.ensure_collection(vector_size=vector_size):
            return 0

        points = []
        meta = doc_metadata or {}

        for c in valid_chunks:
            chunk_idx = c.get("chunk_index", 0)
            chunk_id = c.get("chunk_id") or f"{sha256_hash}_{chunk_idx}"
            
            # Deterministic UUID from chunk identity
            point_uuid = str(uuid.uuid5(REPO_NAMESPACE_UUID, f"{sha256_hash}:{chunk_idx}"))

            payload = {
                "chunk_id": chunk_id,
                "sha256_hash": sha256_hash,
                "chunk_index": chunk_idx,
                "chunk_text": c.get("chunk_text", ""),
                "token_count": c.get("token_count", 0),
                "canonical_filename": meta.get("canonical_filename", c.get("canonical_filename", "")),
                "doc_type": meta.get("doc_type", c.get("doc_type", "doc")),
                "doc_date": meta.get("doc_date", c.get("doc_date", "")),
                "maturity_score": meta.get("maturity_score", c.get("maturity_score", 0.0)),
                "lifecycle_status": meta.get("lifecycle_status", c.get("lifecycle_status", "draft")),
            }

            points.append(self._models.PointStruct(
                id=point_uuid,
                vector=c["embedding"],
                payload=payload
            ))

        try:
            self._client.upsert(
                collection_name=self.collection_name,
                points=points
            )
            return len(points)
        except Exception as exc:
            logger.error("Failed to upsert %d chunks into Qdrant: %s", len(points), exc)
            return 0

    def search_similar_chunks(self,
                              query_vector: List[float],
                              limit: int = 10,
                              min_similarity: float = 0.25) -> List[Dict[str, Any]]:
        """Searches nearest neighbor chunks in Qdrant via HNSW indexing."""
        if not self.is_available or not query_vector:
            return []

        if not self.ensure_collection(vector_size=len(query_vector)):
            return []

        try:
            # Query Qdrant
            # Supports qdrant-client >= 1.7 search / query_points
            if hasattr(self._client, "search"):
                hits = self._client.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    limit=limit,
                    score_threshold=min_similarity
                )
            else:
                response = self._client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    limit=limit,
                    score_threshold=min_similarity
                )
                hits = response.points

            results = []
            for h in hits:
                payload = dict(h.payload or {})
                score = float(h.score)
                payload["similarity_score"] = score
                results.append(payload)

            return results
        except Exception as exc:
            logger.error("Qdrant similarity search failed: %s", exc)
            return []

    def delete_document_chunks(self, sha256_hash: str) -> bool:
        """Removes all indexed chunks associated with a document sha256 hash."""
        if not self.is_available:
            return False

        try:
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=self._models.FilterSelector(
                    filter=self._models.Filter(
                        must=[
                            self._models.FieldCondition(
                                key="sha256_hash",
                                match=self._models.MatchValue(value=sha256_hash)
                            )
                        ]
                    )
                )
            )
            return True
        except Exception as exc:
            logger.error("Failed deleting chunks for doc %s from Qdrant: %s", sha256_hash, exc)
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Returns collection and server telemetry from Qdrant."""
        if not self.is_available:
            return {
                "available": False,
                "status": "offline_or_disabled",
                "engine": "qdrant",
                "collection": self.collection_name,
                "url": self.url
            }

        try:
            info = self._client.get_collection(collection_name=self.collection_name)
            return {
                "available": True,
                "status": "active",
                "engine": "qdrant",
                "collection": self.collection_name,
                "url": self.url,
                "vectors_count": getattr(info, "vectors_count", getattr(info, "points_count", 0)),
                "indexed_vectors_count": getattr(info, "indexed_vectors_count", 0),
                "segments_count": getattr(info, "segments_count", 0),
                "status_str": str(getattr(info, "status", "green")),
            }
        except Exception as exc:
            return {
                "available": True,
                "status": "collection_not_created_yet",
                "engine": "qdrant",
                "collection": self.collection_name,
                "url": self.url,
                "detail": str(exc)
            }

    def clear_collection(self) -> bool:
        """Delete and clear the collection for clean re-indexing."""
        if not self.is_available:
            return False
        try:
            self._client.delete_collection(collection_name=self.collection_name)
            self._initialized_collections.discard(self.collection_name)
            logger.info("Qdrant collection '%s' cleared.", self.collection_name)
            return True
        except Exception as exc:
            logger.warning("Failed to delete Qdrant collection '%s': %s", self.collection_name, exc)
            return False

