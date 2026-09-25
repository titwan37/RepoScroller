"""Hybrid GraphRAG Engine combining dense vector retrieval, lexical BM25, and Knowledge Graph expansion."""

import logging
from typing import Dict, Any, List, Optional
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.ledger.vector_store import VectorStore
from reposcroller.ledger.graph_store import PropertyGraphStore
from reposcroller.ai.embeddings import EmbeddingAdapter

logger = logging.getLogger("reposcroller.graph_rag")


class GraphRAGQueryEngine:
    """Executes 3-signal hybrid retrieval (Dense Vector + Lexical BM25 + Graph Expansion) with RRF fusion."""

    def __init__(self,
                 repository: Optional[DocumentRepository] = None,
                 vector_store: Optional[VectorStore] = None,
                 graph_store: Optional[PropertyGraphStore] = None,
                 embedding_adapter: Optional[EmbeddingAdapter] = None):
        self.repo = repository or DocumentRepository()
        self.embedder = embedding_adapter or EmbeddingAdapter()
        self.vector_store = vector_store or VectorStore(repository=self.repo, embedding_adapter=self.embedder)
        self.graph_store = graph_store or PropertyGraphStore(repository=self.repo)

    def reciprocal_rank_fusion(self,
                               dense_hits: List[Dict[str, Any]],
                               sparse_hits: List[Dict[str, Any]],
                               k: int = 60) -> List[Dict[str, Any]]:
        """Merge ranked lists using Reciprocal Rank Fusion formula: RRF(d) = sum(1 / (k + rank))."""
        scores: Dict[str, float] = {}
        doc_map: Dict[str, Dict[str, Any]] = {}

        # Dense rank contributions
        for rank, hit in enumerate(dense_hits):
            sha = hit["sha256_hash"]
            scores[sha] = scores.get(sha, 0.0) + (1.0 / (k + rank + 1))
            if sha not in doc_map:
                doc_map[sha] = hit

        # Sparse rank contributions
        for rank, hit in enumerate(sparse_hits):
            sha = hit["sha256_hash"]
            scores[sha] = scores.get(sha, 0.0) + (1.0 / (k + rank + 1))
            if sha not in doc_map:
                doc_map[sha] = hit

        fused = []
        for sha, score in scores.items():
            entry = dict(doc_map[sha])
            entry["rrf_score"] = score
            fused.append(entry)

        fused.sort(key=lambda x: x["rrf_score"], reverse=True)
        return fused

    def query(self,
              query_text: str,
              top_k: int = 5,
              expand_graph_hops: int = 1) -> Dict[str, Any]:
        """Run complete GraphRAG query with vector search, FTS5 lexical match, and graph neighborhood expansion."""
        if not query_text or not query_text.strip():
            return {"query": query_text, "results": [], "graph_context": []}

        # 1. Signal A: Dense Semantic Vector Search
        dense_hits = self.vector_store.search_similar_chunks(query_text, limit=top_k * 2)

        # 2. Signal B: Lexical Sparse Search (FTS5 BM25)
        sparse_hits = self.repo.search_keyword_fts(query_text, limit=top_k * 2)

        # 3. Reciprocal Rank Fusion
        fused_candidates = self.reciprocal_rank_fusion(dense_hits, sparse_hits, k=60)
        top_candidates = fused_candidates[:top_k]

        # 4. Signal C: Knowledge Graph Neighborhood Expansion
        graph_entities = []
        seen_nodes = set()

        for cand in top_candidates:
            sha = cand["sha256_hash"]
            entities = self.graph_store.get_document_entities(sha)
            for ent in entities:
                n_id = ent["node_id"]
                if n_id not in seen_nodes:
                    seen_nodes.add(n_id)
                    neighborhood = self.graph_store.expand_entity_neighborhood(n_id, max_hops=expand_graph_hops)
                    graph_entities.append({
                        "node": ent,
                        "neighborhood": neighborhood
                    })

        # 5. Format Answer / Context summary
        context_chunks = [c.get("chunk_text") or c.get("text_snippet", "") for c in top_candidates]

        return {
            "query": query_text,
            "top_candidates": top_candidates,
            "context_chunks": context_chunks,
            "graph_entities": graph_entities,
            "retrieval_signals": {
                "dense_hits_count": len(dense_hits),
                "sparse_hits_count": len(sparse_hits),
                "fused_candidates_count": len(top_candidates),
                "graph_entities_expanded": len(graph_entities)
            }
        }
