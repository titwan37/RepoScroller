"""REST API routes for Knowledge Base sidecar worker and semantic vector retrieval."""

from typing import Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel
from backend.config import settings
from backend.ledger.repository import DocumentRepository
from backend.ledger.vector_store import VectorStore
from backend.ledger.graph_store import PropertyGraphStore
from backend.ai.sidecar_worker import KnowledgeBaseSidecarWorker
from backend.agents.graph_rag import GraphRAGQueryEngine

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
    top_k: Optional[int] = 25
    expand_graph_hops: Optional[int] = 1


@router.get("/stats")
def get_sidecar_stats():
    """Retrieve queue status, vector indexing, graph statistics, continuous worker state, and throughput metrics."""
    from backend.ai.telemetry import workload_telemetry
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
        "pipeline": worker_status.get("pipeline", {}),
        "files_per_minute": throughput["files_per_minute"],
        "chunks_per_minute": throughput["chunks_per_minute"],
        "tokens_processed": throughput["total_tokens"],
        "last_batch_tokens": throughput["last_batch_tokens"],
        "checkpoints": throughput["checkpoints"],
        "payload_mib": throughput["payload_mib"],
        "model": workload_telemetry.active_tier_model or settings.OLLAMA_EMBEDDING_MODEL,
        "embed_url": workload_telemetry.active_tier_url or settings.embed_url,
        "chat_model": settings.OLLAMA_MODEL_PC2,
        "chat_url": settings.chat_url,
        "dual_models": {
            "embedding": workload_telemetry.active_tier_model or settings.OLLAMA_EMBEDDING_MODEL,
            "chat": settings.OLLAMA_MODEL_PC2
        },
        "validation": worker_status.get("validation", {}),
        "embedding_tier": {
            "tier": tier,
            "color": tier_color,
            "label": tier_label,
            "active_url": workload_telemetry.active_tier_url,
            "active_model": workload_telemetry.active_tier_model,
            "fallback_reason": workload_telemetry.last_fallback_reason
        }
    }


class ValidateEntitiesRequest(BaseModel):
    limit: Optional[int] = 50
    dry_run: Optional[bool] = False
    deterministic_only: Optional[bool] = False
    run_llm: Optional[bool] = True


@router.post("/validate-entities")
@router.post("/entities/validate")
def validate_knowledge_graph_entities(req: Optional[ValidateEntitiesRequest] = None):
    """Trigger on-demand Knowledge Graph entity validation and hallucination pruning."""
    limit = (req.limit if req and req.limit is not None else 50)
    dry_run = (req.dry_run if req and req.dry_run is not None else False)
    deterministic_only = (req.deterministic_only if req and req.deterministic_only is not None else False)
    run_llm = not deterministic_only if (req is None or req.run_llm is None) else req.run_llm

    res = _worker.validate_entities(
        limit=limit,
        dry_run=dry_run,
        run_deterministic=True,
        run_llm=run_llm
    )
    return {
        "status": "success",
        "result": res
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
def get_3d_knowledge_universe(
    limit: int = Query(default=1000, ge=10, le=5000),
    layout: Optional[str] = Query(default="spatial", description="Graph layout topology: 'spatial' or 'thematic'"),
    location: Optional[str] = Query(default=None, description="Filter nodes matching or linked to location"),
    org: Optional[str] = Query(default=None, description="Filter nodes matching or linked to organization"),
    organization: Optional[str] = Query(default=None, description="Alias for org filter"),
    person: Optional[str] = Query(default=None, description="Filter nodes matching or linked to person"),
    author: Optional[str] = Query(default=None, description="Alias for person filter"),
    node_type: Optional[str] = Query(default=None, description="Filter by entity node_type"),
    type: Optional[str] = Query(default=None, description="Alias for node_type filter"),
    cluster: Optional[int] = Query(default=None, description="Filter by cluster ID (0-6)"),
    level: Optional[str] = Query(default=None, description="Geographic hierarchy rollup level: 'canton' or 'municipality'"),
    doc_sha: Optional[str] = Query(default=None, description="Filter by document SHA-256 hash"),
    sha256: Optional[str] = Query(default=None, description="Alias for doc_sha"),
    document: Optional[str] = Query(default=None, description="Alias for doc_sha"),
    theme: Optional[str] = Query(default=None, description="Filter by taxonomy theme ID or slug"),
    q: Optional[str] = Query(default=None, description="General search query filter"),
    query: Optional[str] = Query(default=None, description="Alias for search query"),
    search: Optional[str] = Query(default=None, description="Alias for search query"),
):
    """Retrieve 3D WebGL knowledge graph universe with dynamic filtering and unsupervised topological coordinates."""
    filters = {}
    if location:
        filters["location"] = location.strip()
    if level:
        filters["level"] = level.strip().lower()
    if org or organization:
        filters["org"] = (org or organization).strip()
    if person or author:
        filters["person"] = (person or author).strip()
    if node_type or type:
        filters["node_type"] = (node_type or type).strip()
    if cluster is not None:
        filters["cluster"] = cluster
    if doc_sha or sha256 or document:
        filters["doc_sha"] = (doc_sha or sha256 or document).strip()
    if theme:
        filters["theme"] = theme.strip()
    if q or query or search:
        filters["q"] = (q or query or search).strip()

    data = _graph_store.get_3d_knowledge_universe(
        limit=limit,
        filters=filters if filters else None,
        layout=layout or "spatial"
    )
    return {
        "status": "success",
        **data
    }


@router.post("/theme-backfill")
def trigger_theme_backfill():
    """Backfill taxonomy theme hubs and CATEGORIZED_AS links for already-ingested documents."""
    result = _graph_store.backfill_theme_links()
    return {
        "status": "success",
        **result
    }


@router.post("/financial-pillars-backfill")
def trigger_financial_pillars_backfill():
    """Backfill contractual financial pillars (rent, salary, mortgage, fees, fines, interest, insurance)."""
    result = _graph_store.backfill_financial_pillars()
    return {
        "status": "success",
        **result
    }


@router.post("/geo-links-backfill")
def trigger_geo_links_backfill():
    """Synchronize geographic and edge document links into document_entity_links."""
    result = _graph_store.backfill_geo_entity_links()
    return {
        "status": "success",
        **result
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


@router.get("/graph/node/{node_id:path}")
@router.get("/graph/node")
@router.get("/node-neighborhood")
def get_graph_node_neighborhood(
    node_id: Optional[str] = None,
    id: Optional[str] = Query(default=None, description="Entity node identifier"),
    hops: int = Query(default=1, ge=1, le=3, description="Neighborhood expansion hop radius")
):
    """Retrieve an entity or document node's connected neighborhood and associated documents."""
    target_id = (node_id or id or "").strip()
    if not target_id:
        return {
            "node_id": "",
            "outgoing_relations": [],
            "incoming_relations": [],
            "associated_documents": [],
        }
    neighborhood = _graph_store.expand_entity_neighborhood(node_id=target_id, max_hops=hops)
    return neighborhood


@router.get("/graph-rag")
@router.post("/graph-rag")
def execute_graph_rag_query(
    req: Optional[GraphRAGRequest] = None,
    query: Optional[str] = Query(default=None),
    top_k: Optional[int] = Query(default=25, ge=1, le=100),
    expand_graph_hops: Optional[int] = Query(default=1, ge=0, le=3)
):
    """Execute hybrid GraphRAG retrieval combining dense vectors, FTS5 BM25, and graph expansion (supports GET and POST)."""
    q = (req.query if req and req.query else query) or ""
    k = (req.top_k if req and req.top_k is not None else top_k) or 25
    hops = (req.expand_graph_hops if req and req.expand_graph_hops is not None else expand_graph_hops) or 1
    
    res = _graph_rag.query(
        query_text=q,
        top_k=k,
        expand_graph_hops=hops
    )
    return res


# Dedicated /rag router alias for standard RAG query and search conventions
rag_router = APIRouter(prefix="/rag", tags=["GraphRAG"])


@rag_router.get("/search")
@rag_router.get("/query")
@rag_router.post("/search")
@rag_router.post("/query")
def execute_rag_search_alias(
    req: Optional[GraphRAGRequest] = None,
    q: Optional[str] = Query(default=None, description="Search query string"),
    query: Optional[str] = Query(default=None, description="Alternative query parameter"),
    top_k: Optional[int] = Query(default=25, ge=1, le=100),
    expand_graph_hops: Optional[int] = Query(default=1, ge=0, le=3)
):
    """Execute hybrid GraphRAG retrieval via /api/v1/rag/search (supports GET/POST with ?q= or ?query=)."""
    query_text = (req.query if req and req.query else (q or query)) or ""
    k = (req.top_k if req and req.top_k is not None else top_k) or 25
    hops = (req.expand_graph_hops if req and req.expand_graph_hops is not None else expand_graph_hops) or 1

    return _graph_rag.query(
        query_text=query_text,
        top_k=k,
        expand_graph_hops=hops
    )




