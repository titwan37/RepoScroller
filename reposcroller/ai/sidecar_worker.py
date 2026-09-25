"""Knowledge Base Sidecar Worker for asynchronous document chunking, vector embedding, and continuous pipeline processing."""

import time
import logging
import threading
from typing import Dict, Any, Optional, List
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

        # Continuous Worker State
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.is_running: bool = False
        self.session_start_time: Optional[float] = None
        self.session_docs_processed: int = 0
        self.session_chunks_embedded: int = 0

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
            indexed_count = self.vector_store.index_document_chunks(
                sha256_hash=sha,
                chunks=chunks,
                doc_metadata=doc_record
            )

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
            from reposcroller.ai.telemetry import workload_telemetry
            workload_telemetry.record_document_completed(count=1, chunks=indexed_count)

            with self._lock:
                self.session_docs_processed += 1
                self.session_chunks_embedded += indexed_count

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
        """Fetch and process a batch of pending documents using high-throughput GPU batching and single-transaction persistence."""
        pending_items = self.repo.fetch_pending_kb_queue(limit=limit)
        if not pending_items:
            return {"processed_count": 0, "results": []}

        # 1. Mark batch as processing
        batch_shas = [item["sha256_hash"] for item in pending_items]
        self.repo.mark_kb_queue_batch_status(batch_shas, "processing")

        docs_to_embed: List[tuple] = []
        doc_graphs = []
        results = []
        completed_shas = []
        total_batch_chunks = 0

        # 2. In-memory chunking and heuristic graph extraction
        for item in pending_items:
            sha = item["sha256_hash"]
            fname = item.get("canonical_filename", "")
            doc_type = item.get("doc_type", "")
            doc_date = item.get("doc_date", "")

            try:
                full_text = self.repo.get_document_full_text(sha)
                if not full_text:
                    full_text = item.get("text_snippet", "")

                if not full_text:
                    completed_shas.append(sha)
                    results.append({"sha256": sha, "status": "skipped_no_text", "chunks_count": 0, "entities_count": 0})
                    continue

                chunks = self.chunker.chunk_document(
                    text=full_text,
                    sha256_hash=sha,
                    canonical_filename=fname,
                    doc_type=doc_type,
                    doc_date=doc_date,
                )
                docs_to_embed.append((sha, chunks, item))

                doc_graph = self.graph_extractor.extract_knowledge_graph(
                    text=full_text,
                    sha256_hash=sha,
                    filename=fname,
                    doc_type=doc_type,
                    doc_date=doc_date,
                )
                doc_graphs.append(doc_graph)
                completed_shas.append(sha)

                results.append({
                    "sha256": sha,
                    "status": "completed",
                    "chunks_count": len(chunks),
                    "entities_count": len(doc_graph.nodes),
                    "edges_count": len(doc_graph.edges),
                    "canonical_filename": fname
                })
            except Exception as e:
                logger.error(f"Error in batch prep for KB document {sha}: {e}")
                self.repo.mark_kb_queue_status(sha, "failed", error_message=str(e))
                results.append({"sha256": sha, "status": "failed", "error": str(e)})

        # 3. Batch Vector Embedding on Remote GPU & Single Transaction SQLite Commit
        if docs_to_embed:
            total_batch_chunks = self.vector_store.index_batch_document_chunks(docs_to_embed)

        # 4. Batch Knowledge Graph Persistence
        if doc_graphs:
            self.graph_store.save_graphs_batch(doc_graphs)

        # 5. Batch Mark Completed
        if completed_shas:
            self.repo.mark_kb_queue_batch_status(completed_shas, "completed")
            from reposcroller.ai.telemetry import workload_telemetry
            workload_telemetry.record_document_completed(count=len(completed_shas), chunks=total_batch_chunks)

        with self._lock:
            self.session_docs_processed += len(completed_shas)
            self.session_chunks_embedded += total_batch_chunks

        return {
            "processed_count": len(results),
            "results": results,
        }

    def start_continuous_worker(self, poll_interval: float = 2.0) -> Dict[str, Any]:
        """Start long-term continuous processing in a background daemon thread."""
        with self._lock:
            if self.is_running and self._thread and self._thread.is_alive():
                return {
                    "status": "already_running",
                    "message": "Sidecar indexing pipeline is already active.",
                    "session_docs_processed": self.session_docs_processed,
                    "session_chunks_embedded": self.session_chunks_embedded
                }

            self._stop_event.clear()
            self.is_running = True
            self.session_start_time = time.time()
            self.session_docs_processed = 0
            self.session_chunks_embedded = 0

            self._thread = threading.Thread(
                target=self._run_loop,
                args=(poll_interval,),
                name="SidecarContinuousWorker",
                daemon=True
            )
            self._thread.start()
            logger.info(f"Sidecar Indexing Pipeline continuous processing STARTED. Embedding Model: {settings.OLLAMA_EMBEDDING_MODEL} on {settings.embed_url}")

            return {
                "status": "started",
                "message": f"Continuous sidecar indexing started using {settings.OLLAMA_EMBEDDING_MODEL}.",
                "start_time": time.strftime("%H:%M:%S", time.localtime(self.session_start_time)),
                "embed_url": settings.embed_url
            }

    def stop_continuous_worker(self) -> Dict[str, Any]:
        """Stop continuous background processing and return complete session summary."""
        with self._lock:
            if not self.is_running:
                return {
                    "status": "not_running",
                    "message": "Sidecar indexing pipeline is not currently running.",
                    "session_docs_processed": 0,
                    "session_chunks_embedded": 0,
                    "duration_seconds": 0
                }

            self._stop_event.set()
            self.is_running = False

            duration = time.time() - (self.session_start_time or time.time())
            mins, secs = divmod(int(duration), 60)
            duration_fmt = f"{mins}m {secs}s" if mins else f"{secs}s"

            docs = self.session_docs_processed
            chunks = self.session_chunks_embedded

            logger.info(f"Sidecar Indexing Pipeline STOPPED. Processed {docs} documents ({chunks} chunks/vectors) in {duration_fmt}.")

            return {
                "status": "stopped",
                "message": f"Sidecar indexing stopped. Processed {docs} documents ({chunks} vectors) in {duration_fmt}.",
                "session_docs_processed": docs,
                "session_chunks_embedded": chunks,
                "duration_seconds": round(duration, 1),
                "duration_formatted": duration_fmt
            }

    def get_continuous_status(self) -> Dict[str, Any]:
        """Get live status and progress counters of the continuous worker."""
        with self._lock:
            now = time.time()
            uptime_seconds = int(now - self.session_start_time) if (self.is_running and self.session_start_time) else 0
            mins, secs = divmod(uptime_seconds, 60)
            uptime_fmt = f"{mins}m {secs}s" if mins else f"{secs}s"

            return {
                "is_running": self.is_running and bool(self._thread and self._thread.is_alive()),
                "session_docs_processed": self.session_docs_processed,
                "session_chunks_embedded": self.session_chunks_embedded,
                "uptime_seconds": uptime_seconds,
                "uptime_formatted": uptime_fmt,
                "start_time": time.strftime("%H:%M:%S", time.localtime(self.session_start_time)) if self.session_start_time else None
            }

    def _run_loop(self, poll_interval: float = 2.0) -> None:
        """Internal worker loop running continuously until stop event is signaled."""
        logger.info(f"Sidecar worker thread active (poll interval: {poll_interval}s)...")
        last_reported_hundred = 0
        while not self._stop_event.is_set():
            try:
                batch_res = self.process_pending_batch(limit=settings.KB_SIDECAR_BATCH_SIZE)
                if batch_res["processed_count"] > 0:
                    current_hundred = self.session_docs_processed // 100
                    if current_hundred > last_reported_hundred:
                        last_reported_hundred = current_hundred
                        logger.info(f"⚡ Sidecar Milestone: {self.session_docs_processed} docs processed ({self.session_chunks_embedded} chunks/vectors in VRAM) | Model: {settings.OLLAMA_EMBEDDING_MODEL}")
                else:
                    if self.session_docs_processed > 0 and self.session_docs_processed != last_reported_hundred * 100:
                        last_reported_hundred = self.session_docs_processed // 100
                        logger.info(f"✅ Sidecar Cycle Complete: All queued documents processed ({self.session_docs_processed} total docs, {self.session_chunks_embedded} chunks indexed).")
                    self._stop_event.wait(timeout=poll_interval)
            except Exception as e:
                logger.error(f"Error in KB Sidecar loop: {e}")
                self._stop_event.wait(timeout=poll_interval)

        logger.info("Sidecar continuous loop exited gracefully.")

    def run_worker_loop(self, poll_interval: float = 3.0, stop_event=None) -> None:
        """CLI entrypoint for standalone background sidecar daemon."""
        from reposcroller.ai.telemetry import workload_telemetry
        logger.info(f"Knowledge Base Sidecar daemon started | Model: {settings.OLLAMA_EMBEDDING_MODEL} | Target: {settings.embed_url}")
        last_reported_hundred = 0
        is_idle_reported = False

        while not (stop_event and stop_event.is_set()):
            try:
                batch_res = self.process_pending_batch(limit=settings.KB_SIDECAR_BATCH_SIZE)
                processed = batch_res.get("processed_count", 0)
                if processed > 0:
                    is_idle_reported = False
                    batch_chunks = sum(r.get("chunks_count", 0) for r in batch_res.get("results", []))
                    tier_label = workload_telemetry.active_tier_label
                    logger.info(
                        f"⚡ [BATCH] Processed {processed} docs ({batch_chunks} chunks) -> Session: {self.session_docs_processed} docs ({self.session_chunks_embedded} chunks) | Tier: {tier_label}"
                    )

                    current_hundred = self.session_docs_processed // 100
                    if current_hundred > last_reported_hundred:
                        last_reported_hundred = current_hundred
                        logger.info(
                            f"🏆 [MILESTONE] {self.session_docs_processed} documents indexed into Knowledge Base & Vector Index!"
                        )
                else:
                    if not is_idle_reported:
                        logger.info("⏳ [IDLE] All queued documents processed. Waiting for new files...")
                        is_idle_reported = True
                    time.sleep(poll_interval)
            except Exception as e:
                logger.error(f"Error in standalone KB Sidecar loop: {e}")
                time.sleep(poll_interval)

