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
        dense_ranks: Dict[str, int] = {}
        dense_scores: Dict[str, float] = {}
        sparse_ranks: Dict[str, int] = {}

        # Dense rank contributions
        for rank, hit in enumerate(dense_hits):
            sha = hit["sha256_hash"]
            scores[sha] = scores.get(sha, 0.0) + (1.0 / (k + rank + 1))
            dense_ranks[sha] = rank + 1
            dense_scores[sha] = hit.get("similarity_score", 0.0)
            if sha not in doc_map:
                doc_map[sha] = hit

        # Sparse rank contributions
        for rank, hit in enumerate(sparse_hits):
            sha = hit["sha256_hash"]
            scores[sha] = scores.get(sha, 0.0) + (1.0 / (k + rank + 1))
            sparse_ranks[sha] = rank + 1
            if sha not in doc_map:
                doc_map[sha] = hit

        fused = []
        for sha, score in scores.items():
            raw_entry = doc_map[sha]
            entry = dict(raw_entry)
            entry["rrf_score"] = score
            entry["dense_rank"] = dense_ranks.get(sha)
            entry["dense_similarity"] = dense_scores.get(sha)
            entry["sparse_rank"] = sparse_ranks.get(sha)
            fused.append(entry)

        fused.sort(key=lambda x: x["rrf_score"], reverse=True)
        return fused

    def query(self,
              query_text: str,
              top_k: int = 5,
              expand_graph_hops: int = 1) -> Dict[str, Any]:
        """Run complete GraphRAG query with vector search, FTS5 lexical match, and graph neighborhood expansion."""
        if not query_text or not query_text.strip():
            return {
                "query": query_text,
                "ranked_results": [],
                "top_candidates": [],
                "context_chunks": [],
                "graph_entities": [],
                "retrieval_signals": {
                    "dense_hits_count": 0,
                    "sparse_hits_count": 0,
                    "fused_candidates_count": 0,
                    "graph_entities_expanded": 0
                }
            }

        try:
            # 1. Signal A: Dense Semantic Vector Search
            dense_hits = self.vector_store.search_similar_chunks(query_text, limit=top_k * 2)

            # 2. Signal B: Lexical Sparse Search (FTS5 BM25)
            sparse_hits = self.repo.search_keyword_fts(query_text, limit=top_k * 2)

            # 3. Reciprocal Rank Fusion
            fused_candidates = self.reciprocal_rank_fusion(dense_hits, sparse_hits, k=60)
            top_fused = fused_candidates[:top_k]
        except Exception as exc:
            logger.error(f"GraphRAG retrieval error for query '{query_text}': {exc}")
            raise


        # 4. Signal C: Knowledge Graph Neighborhood Expansion & Enrichment
        graph_entities = []
        seen_nodes = set()
        ranked_results = []

        for cand in top_fused:
            sha = cand["sha256_hash"]
            doc_entities = self.graph_store.get_document_entities(sha)
            
            for ent in doc_entities:
                n_id = ent["node_id"]
                if n_id not in seen_nodes:
                    seen_nodes.add(n_id)
                    neighborhood = self.graph_store.expand_entity_neighborhood(n_id, max_hops=expand_graph_hops)
                    graph_entities.append({
                        "node": ent,
                        "neighborhood": neighborhood
                    })

            has_dense = cand.get("dense_rank") is not None
            has_sparse = cand.get("sparse_rank") is not None

            # Formulate structured result
            result_item = {
                "sha256_hash": sha,
                "composite_score": cand.get("rrf_score", 0.0),
                "document": {
                    "sha256_hash": sha,
                    "canonical_filename": cand.get("canonical_filename", ""),
                    "doc_type": cand.get("doc_type", "doc"),
                    "doc_date": cand.get("doc_date", ""),
                    "maturity_score": cand.get("maturity_score", 0.0),
                    "lifecycle_status": cand.get("lifecycle_status", "draft"),
                    "text_snippet": cand.get("text_snippet", "")
                },
                "chunk": {
                    "chunk_id": cand.get("chunk_id", f"{sha}_0"),
                    "chunk_text": cand.get("chunk_text") or cand.get("text_snippet", ""),
                    "token_count": cand.get("token_count", len((cand.get("chunk_text") or cand.get("text_snippet", "")).split())),
                    "canonical_filename": cand.get("canonical_filename", "")
                },
                "signals": {
                    "dense_vector_match": has_dense,
                    "vector_similarity": cand.get("dense_similarity") or 0.0,
                    "lexical_fts_match": has_sparse,
                    "bm25_rank": cand.get("sparse_rank"),
                    "graph_neighborhood_expansion": len(doc_entities) > 0,
                    "connected_entities_count": len(doc_entities),
                    "entities": [e.get("node_id") for e in doc_entities]
                }
            }
            ranked_results.append(result_item)

        # 5. Context chunks summary
        context_chunks = [r["chunk"]["chunk_text"] for r in ranked_results]

        return {
            "query": query_text,
            "ranked_results": ranked_results,
            "top_candidates": ranked_results,
            "context_chunks": context_chunks,
            "graph_entities": graph_entities,
            "retrieval_signals": {
                "dense_hits_count": len(dense_hits),
                "sparse_hits_count": len(sparse_hits),
                "fused_candidates_count": len(ranked_results),
                "graph_entities_expanded": len(graph_entities)
            }
        }
