"""Vector store manager for dense semantic similarity search over document chunks."""

import json
from typing import List, Dict, Any, Optional
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.ai.embeddings import EmbeddingAdapter, cosine_similarity


class VectorStore:
    """Manages dense embedding persistence and semantic search across document chunks."""

    def __init__(self,
                 repository: Optional[DocumentRepository] = None,
                 embedding_adapter: Optional[EmbeddingAdapter] = None):
        self.repo = repository or DocumentRepository()
        self.embedder = embedding_adapter or EmbeddingAdapter()

    def index_document_chunks(self,
                              sha256_hash: str,
                              chunks: List[Dict[str, Any]]) -> int:
        """Computes embeddings for chunks if missing and persists them into the ledger database."""
        if not chunks:
            return 0

        # Collect texts needing embeddings
        texts_to_embed = [c["chunk_text"] for c in chunks if not c.get("embedding")]
        if texts_to_embed:
            embeddings = self.embedder.embed_batch(texts_to_embed)
            emb_idx = 0
            for c in chunks:
                if not c.get("embedding"):
                    c["embedding"] = embeddings[emb_idx]
                    emb_idx += 1

        self.repo.save_document_chunks(sha256_hash, chunks)
        return len(chunks)

    def search_similar_chunks(self,
                              query: str,
                              limit: int = 10,
                              min_similarity: float = 0.25) -> List[Dict[str, Any]]:
        """Dense semantic search over all indexed document chunks using cosine similarity."""
        if not query or not query.strip():
            return []

        query_emb = self.embedder.embed_text(query)

        # Retrieve all stored chunks with embeddings
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
