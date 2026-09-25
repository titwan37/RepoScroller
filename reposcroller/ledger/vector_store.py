"""Vector store manager for dense semantic similarity search over document chunks.

Supports both embedded SQLite local persistence and optional enterprise-grade
Qdrant HNSW vector search plugin for high-scale document retrieval.
"""

import json
from typing import List, Dict, Any, Optional
from reposcroller.config import settings
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.ai.embeddings import EmbeddingAdapter, cosine_similarity
from reposcroller.ledger.qdrant_plugin import QdrantVectorStorePlugin


class VectorStore:
    """Manages dense embedding persistence and semantic search across document chunks."""

    def __init__(self,
                 repository: Optional[DocumentRepository] = None,
                 embedding_adapter: Optional[EmbeddingAdapter] = None,
                 qdrant_plugin: Optional[QdrantVectorStorePlugin] = None):
        self.repo = repository or DocumentRepository()
        self.embedder = embedding_adapter or EmbeddingAdapter()
        self.qdrant = qdrant_plugin or QdrantVectorStorePlugin()

    def index_document_chunks(self,
                              sha256_hash: str,
                              chunks: List[Dict[str, Any]],
                              doc_metadata: Optional[Dict[str, Any]] = None) -> int:
        """Computes embeddings for chunks if missing, persists into SQLite ledger, and syncs to Qdrant if active."""
        if not chunks:
            return 0
        return self.index_batch_document_chunks([(sha256_hash, chunks, doc_metadata)])

    def index_batch_document_chunks(self,
                                    docs_chunks: List[tuple]) -> int:
        """Computes embeddings for multiple documents in a single GPU batch, persists in SQLite, and syncs to Qdrant."""
        if not docs_chunks:
            return 0

        # 1. Collect all texts needing embeddings across all documents in the batch
        all_texts_to_embed: List[str] = []
        chunk_ptrs: List[Dict[str, Any]] = []

        for sha, chunks, _meta in docs_chunks:
            for c in chunks:
                if not c.get("embedding"):
                    all_texts_to_embed.append(c["chunk_text"])
                    chunk_ptrs.append(c)

        # 2. Single batched embedding forward pass to PC2 CUDA node
        if all_texts_to_embed:
            embeddings = self.embedder.embed_batch(all_texts_to_embed)
            for chunk_obj, emb in zip(chunk_ptrs, embeddings):
                chunk_obj["embedding"] = emb

        # 3. Batch persist in SQLite in a single transaction
        batch_to_save = [(sha, chunks) for sha, chunks, _meta in docs_chunks]
        self.repo.save_batch_document_chunks(batch_to_save)

        # 4. Sync to Qdrant if available
        if self.qdrant.is_available:
            for sha, chunks, doc_meta in docs_chunks:
                self.qdrant.upsert_chunks(sha, chunks, doc_metadata=doc_meta)

        total_chunks = sum(len(chunks) for _, chunks, _ in docs_chunks)
        return total_chunks

    def search_similar_chunks(self,
                              query: str,
                              limit: int = 10,
                              min_similarity: float = 0.25) -> List[Dict[str, Any]]:
        """Dense semantic search over all indexed document chunks.
        
        Prioritizes Qdrant HNSW index if available, falling back smoothly to local SQLite dot-product search.
        """
        if not query or not query.strip():
            return []

        query_emb = self.embedder.embed_text(query)

        # Path A: Fast HNSW retrieval via Qdrant plugin
        if self.qdrant.is_available and settings.VECTOR_STORE_TYPE.lower() == "qdrant":
            qdrant_results = self.qdrant.search_similar_chunks(
                query_vector=query_emb,
                limit=limit,
                min_similarity=min_similarity
            )
            if qdrant_results:
                return qdrant_results

        # Path B: Local SQLite In-Memory Cosine Search
        with self.repo._lock:
            cur = self.repo.conn.cursor()
            cur.execute("""
                SELECT c.chunk_id, c.sha256_hash, c.chunk_index, c.chunk_text, c.token_count, c.embedding_json,
                       dl.canonical_filename, dl.doc_type, dl.doc_date, dl.maturity_score, dl.lifecycle_status
                FROM document_chunks c
                JOIN document_ledger dl ON c.sha256_hash = dl.sha256_hash
                WHERE c.embedding_json IS NOT NULL;
            """)
            rows = cur.fetchall()

        scored_results = []
        for r in rows:
            d = dict(r)
            if not d.get("embedding_json"):
                continue
            try:
                emb = json.loads(d["embedding_json"])
                score = cosine_similarity(query_emb, emb)
                if score >= min_similarity:
                    d["similarity_score"] = score
                    del d["embedding_json"]
                    scored_results.append(d)
            except Exception:
                continue

        scored_results.sort(key=lambda x: x["similarity_score"], reverse=True)
        return scored_results[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """Returns statistics for both SQLite vector table and Qdrant plugin backend."""
        kb_stats = self.repo.get_kb_queue_stats()
        stats = {
            "backend_selected": settings.VECTOR_STORE_TYPE,
            "sqlite": {
                "total_chunks_indexed": kb_stats.get("total_chunks_indexed", 0),
                "total_documents_chunked": kb_stats.get("total_documents_chunked", 0)
            },
            "qdrant": self.qdrant.get_stats()
        }
        return stats

