"""Hybrid Multi-Signal GraphRAG Retrieval Engine with RRF and LangGraph Agentic State Machine."""

import re
import json
import time
import logging
from typing import Dict, Any, List, Optional
import httpx

from backend.config import settings
from backend.agents.state import GraphRAGState
from backend.ledger.repository import DocumentRepository
from backend.ledger.vector_store import VectorStore
from backend.ledger.graph_store import PropertyGraphStore
from backend.ai.embeddings import EmbeddingAdapter
from backend.integrity.simhash import compute_simhash, hamming_distance

from langgraph.graph import StateGraph, END

logger = logging.getLogger("graph_rag")

# Persistent HTTP client with connection pooling to prevent Windows ephemeral TCP port exhaustion [WinError 10055]
_http_client: Optional[httpx.Client] = None


def get_http_client() -> httpx.Client:
    """Retrieve or initialize the thread-safe connection-pooled HTTP client."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.Client(
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=15),
            timeout=httpx.Timeout(timeout=30.0, connect=5.0)
        )
    return _http_client


class CrossEncoderReranker:
    """Reranks fused RRF candidates using a token-level Cross-Encoder or calibrated heuristic fallback."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-large"):
        self.model_name = model_name
        self._model = None
        self._initialized = False

    def _lazy_init(self):
        if not self._initialized:
            try:
                import importlib
                st_mod = importlib.import_module("sentence_transformers")
                cross_encoder_cls = getattr(st_mod, "CrossEncoder", None)
                if cross_encoder_cls:
                    self._model = cross_encoder_cls(self.model_name)
                    logger.info(f"Loaded CrossEncoder model: {self.model_name}")
            except Exception as e:
                logger.debug(f"CrossEncoder '{self.model_name}' not available ({e}). Using calibrated multi-signal fallback reranker.")
                self._model = None
            self._initialized = True

    def rerank(self, query: str, candidates: List[Dict[str, Any]], top_k: int = 6) -> List[Dict[str, Any]]:
        """Prune and reorder top candidates using cross-encoding scores to eliminate context noise."""
        if not candidates:
            return []
        self._lazy_init()

        if self._model:
            try:
                pairs = []
                for c in candidates:
                    chunk_text = c.get("chunk", {}).get("chunk_text") or c.get("document", {}).get("text_snippet") or ""
                    pairs.append([query, chunk_text])
                scores = self._model.predict(pairs)
                for idx, s in enumerate(scores):
                    candidates[idx]["cross_encoder_score"] = float(s)
                candidates.sort(key=lambda x: x["cross_encoder_score"], reverse=True)
                return candidates[:top_k]
            except Exception as exc:
                logger.warning(f"CrossEncoder prediction error: {exc}. Falling back to calibrated reranker.")

        # Calibrated multi-signal fallback reranker
        q_tokens = set(re.findall(r'\w+', query.lower()))
        for c in candidates:
            rrf = c.get("composite_score", 0.0)
            doc = c.get("document", {})
            mat = doc.get("maturity_score", 0.5)
            text = (c.get("chunk", {}).get("chunk_text") or doc.get("text_snippet") or "").lower()
            overlap = sum(1 for tok in q_tokens if tok in text) / max(len(q_tokens), 1)
            is_exact = 1.0 if c.get("signals", {}).get("exact_lookup_match") else 0.0
            is_final = 0.1 if doc.get("lifecycle_status") == "final" else 0.0

            score = (rrf * 40.0) + (overlap * 0.35) + (mat * 0.25) + (is_exact * 0.5) + is_final
            c["cross_encoder_score"] = round(score, 4)

        candidates.sort(key=lambda x: x["cross_encoder_score"], reverse=True)
        return candidates[:top_k]


class GraphRAGQueryEngine:
    """Executes parallel 4-signal hybrid retrieval (Exact/SimHash, BM25, Arctic-Embed2, Graph) + RRF + Cross-Encoder."""

    def __init__(self,
                 repository: Optional[DocumentRepository] = None,
                 vector_store: Optional[VectorStore] = None,
                 graph_store: Optional[PropertyGraphStore] = None,
                 embedding_adapter: Optional[EmbeddingAdapter] = None,
                 reranker: Optional[CrossEncoderReranker] = None):
        self.repo = repository or DocumentRepository()
        self.embedder = embedding_adapter or EmbeddingAdapter()
        self.vector_store = vector_store or VectorStore(repository=self.repo, embedding_adapter=self.embedder)
        self.graph_store = graph_store or PropertyGraphStore(repository=self.repo)
        self.reranker = reranker or CrossEncoderReranker()

    def reciprocal_rank_fusion(self,
                               dense_hits: List[Dict[str, Any]],
                               sparse_hits: List[Dict[str, Any]],
                               exact_hits: Optional[List[Dict[str, Any]]] = None,
                               k: int = 60) -> List[Dict[str, Any]]:
        """Merge ranked candidate lists using Reciprocal Rank Fusion: RRF(d) = sum(1 / (k + rank))."""
        scores: Dict[str, float] = {}
        doc_map: Dict[str, Dict[str, Any]] = {}
        dense_ranks: Dict[str, int] = {}
        dense_scores: Dict[str, float] = {}
        sparse_ranks: Dict[str, int] = {}
        exact_flags: Dict[str, bool] = {}

        # Signal 1: Primary Key & Bitwise Exact Matches get priority injection (rank 0 equivalent bonus)
        if exact_hits:
            for hit in exact_hits:
                sha = hit["sha256_hash"]
                scores[sha] = scores.get(sha, 0.0) + (1.0 / (k + 0.5)) + 0.05  # Anchor boost
                exact_flags[sha] = True
                if sha not in doc_map:
                    doc_map[sha] = hit

        # Signal 2: Dense rank contributions
        for rank, hit in enumerate(dense_hits):
            sha = hit["sha256_hash"]
            scores[sha] = scores.get(sha, 0.0) + (1.0 / (k + rank + 1))
            dense_ranks[sha] = rank + 1
            dense_scores[sha] = hit.get("similarity_score", 0.0)
            if sha not in doc_map:
                doc_map[sha] = hit

        # Signal 3: Sparse rank contributions
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
            entry["dense_similarity"] = dense_scores.get(sha, 0.0)
            entry["sparse_rank"] = sparse_ranks.get(sha)
            entry["exact_lookup_match"] = exact_flags.get(sha, False)
            fused.append(entry)

        fused.sort(key=lambda x: x["rrf_score"], reverse=True)
        return fused

    def query(self,
              query_text: str,
              top_k: int = 25,
              final_top_k: Optional[int] = None,
              expand_graph_hops: int = 1,
              target_sha256: Optional[str] = None) -> Dict[str, Any]:
        """Run parallel 4-signal candidate generation, RRF fusion, and Cross-Encoder reranking."""
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
                    "exact_hits_count": 0,
                    "fused_candidates_count": 0,
                    "graph_entities_expanded": 0
                }
            }

        fetch_limit = max(top_k * 2, 40)
        exact_hits: List[Dict[str, Any]] = []

        try:
            # ---------------------------------------------------------
            # 1. Signal 1: Primary Key & Bitwise Exact Lookup (O(1))
            # ---------------------------------------------------------
            detected_shas = []
            if target_sha256:
                detected_shas.append(target_sha256)

            # Check for 64-char hex SHA256 in query
            hex_matches = re.findall(r'\b[a-fA-F0-9]{64}\b', query_text)
            detected_shas.extend(hex_matches)

            for sha in set(detected_shas):
                doc = self.repo.get_document_by_sha256(sha)
                if doc:
                    exact_hits.append({
                        "sha256_hash": doc["sha256_hash"],
                        "canonical_filename": doc["canonical_filename"],
                        "doc_type": doc["doc_type"],
                        "doc_date": doc["doc_date"],
                        "maturity_score": doc["maturity_score"],
                        "lifecycle_status": doc["lifecycle_status"],
                        "text_snippet": doc["text_snippet"],
                    })

            # Check for exact quoted filename matches
            quoted_filenames = re.findall(r'"([^"]+\.[a-zA-Z0-9]+)"', query_text)
            for qfn in quoted_filenames:
                doc = self.repo.get_document_by_filename(qfn)
                if doc and doc["sha256_hash"] not in [h["sha256_hash"] for h in exact_hits]:
                    exact_hits.append({
                        "sha256_hash": doc["sha256_hash"],
                        "canonical_filename": doc["canonical_filename"],
                        "doc_type": doc["doc_type"],
                        "doc_date": doc["doc_date"],
                        "maturity_score": doc["maturity_score"],
                        "lifecycle_status": doc["lifecycle_status"],
                        "text_snippet": doc["text_snippet"],
                    })

            # Check 64-bit SimHash Hamming distance for near-duplicates (<= 3) and drafts (<= 12)
            if len(query_text.split()) >= 8:
                try:
                    q_sim = compute_simhash(query_text)
                    near_docs = self.repo.find_by_simhash_distance(q_sim, max_distance=12)
                    for nd in near_docs:
                        if nd["sha256_hash"] not in [h["sha256_hash"] for h in exact_hits]:
                            exact_hits.append({
                                "sha256_hash": nd["sha256_hash"],
                                "canonical_filename": nd["canonical_filename"],
                                "doc_type": nd["doc_type"],
                                "doc_date": nd["doc_date"],
                                "maturity_score": nd["maturity_score"],
                                "lifecycle_status": nd["lifecycle_status"],
                                "text_snippet": nd["text_snippet"],
                            })
                except Exception:
                    pass

            # ---------------------------------------------------------
            # 2. Signal 2: Sparse Lexical Keyword Search (SQLite FTS5 / BM25)
            # ---------------------------------------------------------
            sparse_hits = self.repo.search_keyword_fts(query_text, limit=fetch_limit)

            # ---------------------------------------------------------
            # 3. Signal 3: Dense Neural Vector Search (snowflake-arctic-embed2)
            # ---------------------------------------------------------
            dense_hits = self.vector_store.search_similar_chunks(query_text, limit=fetch_limit)

            # ---------------------------------------------------------
            # Fusion: Reciprocal Rank Fusion (k=60)
            # ---------------------------------------------------------
            fused_candidates = self.reciprocal_rank_fusion(
                dense_hits=dense_hits,
                sparse_hits=sparse_hits,
                exact_hits=exact_hits,
                k=60
            )
            top_fused = fused_candidates[:top_k]

        except Exception as exc:
            logger.error(f"GraphRAG candidate retrieval error for query '{query_text}': {exc}")
            raise

        # ---------------------------------------------------------
        # 4. Signal 4: Knowledge Graph Neighborhood Expansion
        # ---------------------------------------------------------
        graph_entities = []
        seen_nodes = set()
        structured_results = []

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
            has_exact = cand.get("exact_lookup_match", False)

            locations = cand.get("locations") or self.repo.get_document_locations(sha)
            primary_path = cand.get("absolute_path") or ""
            if not primary_path and locations:
                primary_loc = next((loc for loc in locations if loc.get("is_primary_source")), locations[0])
                primary_path = primary_loc.get("absolute_path", "")

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
                    "text_snippet": cand.get("text_snippet", ""),
                    "absolute_path": primary_path,
                    "locations": locations
                },
                "chunk": {
                    "chunk_id": cand.get("chunk_id", f"{sha}_0"),
                    "chunk_text": cand.get("chunk_text") or cand.get("text_snippet", ""),
                    "token_count": cand.get("token_count", len((cand.get("chunk_text") or cand.get("text_snippet", "")).split())),
                    "canonical_filename": cand.get("canonical_filename", ""),
                    "absolute_path": primary_path
                },
                "signals": {
                    "exact_lookup_match": has_exact,
                    "dense_vector_match": has_dense,
                    "vector_similarity": cand.get("dense_similarity") or 0.0,
                    "lexical_fts_match": has_sparse,
                    "bm25_rank": cand.get("sparse_rank"),
                    "graph_neighborhood_expansion": len(doc_entities) > 0,
                    "connected_entities_count": len(doc_entities),
                    "entities": [e.get("node_id") for e in doc_entities]
                }
            }
            structured_results.append(result_item)

        # ---------------------------------------------------------
        # 5. Cross-Encoder Reranking
        # ---------------------------------------------------------
        # If final_top_k is explicitly requested (e.g. for LLM prompt context), prune down to top 5-8 chunks.
        # Otherwise, preserve top_k candidates for full list inspection.
        effective_limit = final_top_k if final_top_k is not None else top_k
        reranked_results = self.reranker.rerank(query=query_text, candidates=structured_results, top_k=effective_limit)

        context_chunks = [
            r["chunk"]["chunk_text"] for r in reranked_results
            if r.get("chunk", {}).get("chunk_text")
        ]

        return {
            "query": query_text,
            "ranked_results": reranked_results,
            "top_candidates": reranked_results,
            "context_chunks": context_chunks,
            "graph_entities": graph_entities,
            "retrieval_signals": {
                "exact_hits_count": len(exact_hits),
                "dense_hits_count": len(dense_hits),
                "sparse_hits_count": len(sparse_hits),
                "fused_candidates_count": len(structured_results),
                "final_reranked_count": len(reranked_results),
                "graph_entities_expanded": len(graph_entities)
            }
        }


# =====================================================================
# LangGraph Agentic State Machine
# [User Query] -> [Decontextualizer] -> [Intent Router] -> [Hybrid Retrieval] -> [Context Evaluator] -> [LLM Response]
# =====================================================================

def make_decontextualize_node():
    """LangGraph Node: Resolves pronouns and ambiguous references into a standalone search query."""
    def decontextualize(state: GraphRAGState) -> Dict[str, Any]:
        raw_query = state.get("raw_query", "")
        history = state.get("chat_history", [])

        if not history or not raw_query:
            return {"standalone_query": raw_query}

        # Fast heuristic: if query contains self-sufficient file extensions or no pronouns, skip LLM roundtrip
        has_file_ref = bool(re.search(r'\.(pdf|docx?|txt|md|eml)\b', raw_query, flags=re.IGNORECASE))
        has_pronoun = bool(re.search(r'\b(it|this|that|these|those|they|them|he|she|the document|the contract)\b', raw_query, flags=re.IGNORECASE))

        if has_file_ref and not has_pronoun:
            return {"standalone_query": raw_query}

        prompt = (
            "You are a search query rewriter. Transform the following follow-up question containing "
            "pronouns or ambiguous references into a standalone, fully-specified search query based "
            "on the conversation history.\n\n"
            f"History:\n{json.dumps(history[-3:], ensure_ascii=False)}\n\n"
            f"Follow-up Question: {raw_query}\n"
            "Return ONLY the rewritten standalone query with no explanation."
        )

        try:
            client = get_http_client()
            res = client.post(
                f"{settings.chat_url}/api/generate",
                json={
                    "model": settings.chat_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0, "num_ctx": 1024}
                },
                timeout=5.0
            )
            if res.status_code == 200:
                rewritten = res.json().get("response", "").strip()
                if rewritten and len(rewritten) >= 3:
                    return {"standalone_query": rewritten}
        except Exception as e:
            logger.debug(f"Decontextualizer LLM query rewrite skipped: {e}")

        return {"standalone_query": raw_query}
    return decontextualize


def route_intent_node(state: GraphRAGState) -> Dict[str, Any]:
    """LangGraph Node: Routes query between instant Ledger Existence Check vs Deep Content GraphRAG."""
    query = state.get("standalone_query", state.get("raw_query", "")).lower()

    # Trigger patterns for document existence / duplication checks
    existence_triggers = [
        "do we have", "is there a copy", "is there a version", "duplicate",
        "already have", "already exists", "check if we have", "est-ce qu'on a",
        "existe-t-il", "haben wir", "gibt es eine kopie", "vorhanden"
    ]

    if any(t in query for t in existence_triggers):
        return {"intent": "EXISTENCE_CHECK"}
    return {"intent": "DEEP_CONTENT_QA"}


def make_retrieval_node(engine: GraphRAGQueryEngine):
    """LangGraph Node: Executes 4-signal candidate generation, RRF fusion, and Cross-Encoder reranking."""
    def retrieve(state: GraphRAGState) -> Dict[str, Any]:
        query = state.get("standalone_query", state.get("raw_query", ""))
        target_sha = state.get("target_sha256")

        # Top 5 to 8 context chunks for clean LLM prompt synthesis
        results = engine.query(
            query_text=query,
            target_sha256=target_sha,
            top_k=25,
            final_top_k=6,
            expand_graph_hops=1
        )

        return {
            "retrieval_results": results,
            "context_chunks": results.get("context_chunks", []),
        }
    return retrieve


def context_evaluator_node(state: GraphRAGState) -> Dict[str, Any]:
    """LangGraph Node: Grounding guardrail verifying retrieved evidence sufficiency."""
    chunks = state.get("context_chunks", [])
    # Context is grounded if chunks exist with at least 80 characters of substantive text
    is_grounded = bool(chunks and sum(len(c.strip()) for c in chunks) >= 80)
    return {"is_grounded": is_grounded}


def make_synthesize_node():
    """LangGraph Node: Synthesizes grounded answer or provides transparent refusal if ungrounded."""
    def synthesize(state: GraphRAGState) -> Dict[str, Any]:
        retrieval = state.get("retrieval_results", {})
        ranked = retrieval.get("ranked_results", [])
        sources = [r["document"] for r in ranked if "document" in r]

        # Guardrail: Prevent hallucination if evidence is absent
        if not state.get("is_grounded"):
            return {
                "answer": (
                    "No relevant document clauses or verified records were found in the repository ledger "
                    "to answer this specific question accurately. Please verify the document reference or date."
                ),
                "sources": sources,
                "recommendation": "Ingest the missing primary source document or refine the query reference."
            }

        chunks = state.get("context_chunks", [])
        context_block = "\n---\n".join(chunks[:6])
        query = state.get("standalone_query", state.get("raw_query", ""))

        prompt = (
            "You are RepoScroller's Knowledge Engine, an administrative AI analyzing archival records.\n"
            "Answer the user's question strictly and factually based on the context chunks below.\n"
            "Rules:\n"
            "- If the context explicitly states the answer, summarize it clearly with bullet points and bold terms.\n"
            "- Cite the document filename or date if present in the header.\n"
            "- DO NOT fabricate, extrapolate, or speculate beyond the provided text.\n\n"
            f"Context Chunks:\n{context_block}\n\n"
            f"Question: {query}\n"
            "Answer:"
        )

        try:
            client = get_http_client()
            res = client.post(
                f"{settings.chat_url}/api/generate",
                json={
                    "model": settings.chat_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_ctx": getattr(settings, "OLLAMA_NUM_CTX", 2048)
                    }
                },
                timeout=settings.OLLAMA_TIMEOUT
            )
            if res.status_code == 200:
                answer = res.json().get("response", "").strip()
                if answer:
                    return {
                        "answer": answer,
                        "sources": sources,
                        "recommendation": "Grounded answer compiled from Multi-Signal GraphRAG evidence."
                    }
        except Exception as exc:
            logger.warning(f"Synthesis LLM call failed: {exc}")

        # Fallback snippet summary when LLM is offline
        top_doc = ranked[0]["document"] if ranked else {}
        snip = top_doc.get("text_snippet", "")
        fname = top_doc.get("canonical_filename", "Document")
        fallback_answer = (
            f"**Information retrieved for `{fname}`:**\n\n"
            f"> {snip[:400] or 'Content verified in knowledge index.'}\n\n"
            f"- **Lifecycle Status:** {top_doc.get('lifecycle_status', 'draft')}\n"
            f"- **Storage Path:** `{top_doc.get('absolute_path', 'Repository')}`"
        )
        return {
            "answer": fallback_answer,
            "sources": sources,
            "recommendation": "Document details retrieved from repository ledger."
        }
    return synthesize


def create_graph_rag_workflow(engine: Optional[GraphRAGQueryEngine] = None):
    """Compile the stateful LangGraph agent for conversational GraphRAG."""
    query_engine = engine or GraphRAGQueryEngine()
    workflow = StateGraph(GraphRAGState)

    workflow.add_node("decontextualize", make_decontextualize_node())
    workflow.add_node("router", route_intent_node)
    workflow.add_node("retrieve", make_retrieval_node(query_engine))
    workflow.add_node("evaluate", context_evaluator_node)
    workflow.add_node("synthesize", make_synthesize_node())

    workflow.set_entry_point("decontextualize")
    workflow.add_edge("decontextualize", "router")
    workflow.add_edge("router", "retrieve")
    workflow.add_edge("retrieve", "evaluate")
    workflow.add_edge("evaluate", "synthesize")
    workflow.add_edge("synthesize", END)

    return workflow.compile()
