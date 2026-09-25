"""REST API routes for Knowledge Base sidecar worker and semantic vector retrieval."""

from typing import Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel
from reposcroller.config import settings
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.ledger.vector_store import VectorStore
from reposcroller.ledger.graph_store import PropertyGraphStore
from reposcroller.ai.sidecar_worker import KnowledgeBaseSidecarWorker
from reposcroller.agents.graph_rag import GraphRAGQueryEngine

router = APIRouter(prefix="/sidecar", tags=["Knowledge Base Sidecar"])

_repo = DocumentRepository()
_worker = KnowledgeBaseSidecarWorker(repository=_repo)
_vector_store = VectorStore(repository=_repo)
_graph_store = PropertyGraphStore(repository=_repo)
_graph_rag = GraphRAGQueryEngine(repository=_repo, vector_store=_vector_store, graph_store=_graph_store)


class ProcessRequest(BaseModel):
    limit: Optional[int] = 10


class VectorSearchRequest(BaseModel):
    query: str
    limit: Optional[int] = 10
    min_similarity: Optional[float] = 0.20


class GraphRAGRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5
    expand_graph_hops: Optional[int] = 1


@router.get("/stats")
def get_sidecar_stats():
    """Retrieve queue status, vector indexing, graph statistics, continuous worker state, and throughput metrics."""
    from reposcroller.ai.telemetry import workload_telemetry
    queue_stats = _repo.get_kb_queue_stats()
    graph_stats = _graph_store.get_graph_stats()
    worker_status = _worker.get_continuous_status()
    throughput = workload_telemetry.get_throughput_metrics()
    
    tier = workload_telemetry.active_tier
    tier_color = workload_telemetry.active_tier_color
    tier_label = workload_telemetry.active_tier_label

    return {
        "status": "active",
        "queue": queue_stats,
        "graph": graph_stats,
        "worker": worker_status,
        "throughput": throughput,
        "files_per_minute": throughput["files_per_minute"],
        "chunks_per_minute": throughput["chunks_per_minute"],
        "tokens_processed": throughput["total_tokens"],
        "last_batch_tokens": throughput["last_batch_tokens"],
        "checkpoints": throughput["checkpoints"],
        "payload_mib": throughput["payload_mib"],
        "model": workload_telemetry.active_tier_model or settings.OLLAMA_EMBEDDING_MODEL,
        "embed_url": workload_telemetry.active_tier_url or settings.embed_url,
        "embedding_tier": {
            "tier": tier,
            "color": tier_color,
            "label": tier_label,
            "active_url": workload_telemetry.active_tier_url,
            "active_model": workload_telemetry.active_tier_model,
            "fallback_reason": workload_telemetry.last_fallback_reason
        }
    }


@router.post("/start")
def start_continuous_sidecar_processing(poll_interval: float = Query(2.0, ge=0.5, le=30.0)):
    """Start continuous background sidecar ingestion on the remote PC2 CUDA node."""
    res = _worker.start_continuous_worker(poll_interval=poll_interval)
    return res


@router.post("/stop")
def stop_continuous_sidecar_processing():
    """Stop continuous background sidecar ingestion and return session summary statistics."""
    res = _worker.stop_continuous_worker()
    return res


@router.get("/status")
def get_continuous_sidecar_status():
    """Get live runtime status and counters of the continuous background sidecar worker."""
    return _worker.get_continuous_status()


@router.get("/entities")
def get_grouped_entities(limit_per_type: int = Query(default=200, ge=1, le=1000)):
    """Retrieve all extracted knowledge graph entities grouped by node_type."""
    grouped = _graph_store.get_all_entities_grouped(limit_per_type=limit_per_type)
    return {
        "status": "success",
        "node_types_count": len(grouped),
        "entities_by_type": grouped,
    }


@router.get("/graph-3d")
@router.get("/3d-cluster")
def get_3d_knowledge_universe(limit: int = Query(default=350, ge=50, le=1000)):
    """Retrieve 3D WebGL knowledge graph universe with unsupervised K-Means clustering and PCA coordinates."""
    data = _graph_store.get_3d_knowledge_universe(limit=limit)
    return {
        "status": "success",
        **data
    }



@router.post("/process")
def process_pending_sidecar(req: ProcessRequest):
    """Trigger an immediate processing batch for pending documents in the KB queue."""
    result = _worker.process_pending_batch(limit=req.limit or 10)
    return {
        "status": "success",
        "processed_count": result["processed_count"],
        "results": result["results"],
    }


@router.get("/search")
@router.post("/search")
def search_vector_chunks(
    req: Optional[VectorSearchRequest] = None,
    query: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=10),
    min_similarity: Optional[float] = Query(default=0.20)
):
    """Perform dense semantic similarity search over document chunks (supports GET and POST)."""
    q = (req.query if req and req.query else query) or ""
    lim = (req.limit if req and req.limit is not None else limit) or 10
    min_sim = (req.min_similarity if req and req.min_similarity is not None else min_similarity) or 0.20
    
    hits = _vector_store.search_similar_chunks(
        query=q,
        limit=lim,
        min_similarity=min_sim
    )
    return {
        "query": q,
        "hits_count": len(hits),
        "results": hits,
    }


@router.get("/graph/node/{node_id}")
def get_graph_node_neighborhood(node_id: str, hops: int = Query(default=1, ge=1, le=3)):
    """Retrieve an entity node's connected neighborhood and associated documents."""
    neighborhood = _graph_store.expand_entity_neighborhood(node_id=node_id, max_hops=hops)
    return neighborhood


@router.get("/graph-rag")
@router.post("/graph-rag")
def execute_graph_rag_query(
    req: Optional[GraphRAGRequest] = None,
    query: Optional[str] = Query(default=None),
    top_k: Optional[int] = Query(default=5),
    expand_graph_hops: Optional[int] = Query(default=1)
):
    """Execute hybrid GraphRAG retrieval combining dense vectors, FTS5 BM25, and graph expansion (supports GET and POST)."""
    q = (req.query if req and req.query else query) or ""
    k = (req.top_k if req and req.top_k is not None else top_k) or 5
    hops = (req.expand_graph_hops if req and req.expand_graph_hops is not None else expand_graph_hops) or 1
    
    res = _graph_rag.query(
        query_text=q,
        top_k=k,
        expand_graph_hops=hops
    )
    return res


@router.get("/graph-3d")
@router.get("/3d-cluster")
def get_3d_knowledge_universe(limit: int = Query(default=350, ge=20, le=1000)):
    """Retrieve 3D PCA coordinates, topological clusters, axes of importance, and edges for WebGL GLSL visualization."""
    return _graph_store.get_3d_knowledge_universe(limit=limit)



