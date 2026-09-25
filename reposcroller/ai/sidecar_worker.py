"""Knowledge Base Sidecar Worker for asynchronous document chunking and vector embedding."""

import time
import logging
from typing import Dict, Any, Optional
from reposcroller.config import settings
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.ledger.vector_store import VectorStore
from reposcroller.ledger.graph_store import PropertyGraphStore
from reposcroller.ai.chunker import DocumentChunker
from reposcroller.ai.embeddings import EmbeddingAdapter
from reposcroller.ai.graph_extractor import KnowledgeGraphExtractor

logger = logging.getLogger("reposcroller.kb_sidecar")


class KnowledgeBaseSidecarWorker:
    """Asynchronously processes queued documents to create semantic chunks, dense embeddings, and knowledge graph."""

    def __init__(self,
                 repository: Optional[DocumentRepository] = None,
                 vector_store: Optional[VectorStore] = None,
                 graph_store: Optional[PropertyGraphStore] = None,
                 chunker: Optional[DocumentChunker] = None,
                 embedding_adapter: Optional[EmbeddingAdapter] = None,
                 graph_extractor: Optional[KnowledgeGraphExtractor] = None):
        self.repo = repository or DocumentRepository()
        self.embedder = embedding_adapter or EmbeddingAdapter()
        self.vector_store = vector_store or VectorStore(repository=self.repo, embedding_adapter=self.embedder)
        self.graph_store = graph_store or PropertyGraphStore(repository=self.repo)
        self.chunker = chunker or DocumentChunker()
        self.graph_extractor = graph_extractor or KnowledgeGraphExtractor()

    def process_document(self, doc_record: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single document from the queue: extract text, chunk, embed, extract graph, and persist."""
        sha = doc_record["sha256_hash"]
        fname = doc_record.get("canonical_filename", "")
        doc_type = doc_record.get("doc_type", "")
        doc_date = doc_record.get("doc_date", "")

        try:
            full_text = self.repo.get_document_full_text(sha)
            if not full_text:
                full_text = doc_record.get("text_snippet", "")

            if not full_text:
                self.repo.mark_kb_queue_status(sha, "completed")
                return {"sha256": sha, "status": "skipped_no_text", "chunks_count": 0, "entities_count": 0}

            # 1. Semantic Chunking & Dense Embeddings
            chunks = self.chunker.chunk_document(
                text=full_text,
                sha256_hash=sha,
                canonical_filename=fname,
                doc_type=doc_type,
                doc_date=doc_date,
            )
            indexed_count = self.vector_store.index_document_chunks(sha, chunks)

            # 2. Knowledge Graph Entity & Relationship Extraction
            doc_graph = self.graph_extractor.extract_knowledge_graph(
                text=full_text,
                sha256_hash=sha,
                filename=fname,
                doc_type=doc_type,
                doc_date=doc_date,
            )
            self.graph_store.save_document_graph(doc_graph)

            self.repo.mark_kb_queue_status(sha, "completed")

            return {
                "sha256": sha,
                "status": "completed",
                "chunks_count": indexed_count,
                "entities_count": len(doc_graph.nodes),
                "edges_count": len(doc_graph.edges),
                "canonical_filename": fname
            }
        except Exception as e:
            logger.error(f"Failed processing KB document {sha}: {e}")
            self.repo.mark_kb_queue_status(sha, "failed", error_message=str(e))
            return {"sha256": sha, "status": "failed", "error": str(e)}


    def process_pending_batch(self, limit: int = 10) -> Dict[str, Any]:
        """Fetch and process a batch of pending documents from the KB queue."""
        pending_items = self.repo.fetch_pending_kb_queue(limit=limit)
        if not pending_items:
            return {"processed_count": 0, "results": []}

        results = []
        for item in pending_items:
            res = self.process_document(item)
            results.append(res)

        return {
            "processed_count": len(results),
            "results": results,
        }

    def run_worker_loop(self, poll_interval: float = 3.0, stop_event=None) -> None:
        """Run continuous daemon worker processing pending queue items."""
        logger.info(f"Starting Knowledge Base Sidecar Worker with embedding model '{settings.OLLAMA_EMBEDDING_MODEL}'...")
        while not (stop_event and stop_event.is_set()):
            try:
                batch_res = self.process_pending_batch(limit=settings.KB_SIDECAR_BATCH_SIZE)
                if batch_res["processed_count"] > 0:
                    logger.info(f"KB Sidecar processed {batch_res['processed_count']} documents into vector index.")
                else:
                    time.sleep(poll_interval)
            except Exception as e:
                logger.error(f"Error in KB Sidecar loop: {e}")
                time.sleep(poll_interval)
