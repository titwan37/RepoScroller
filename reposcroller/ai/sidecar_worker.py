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

        # Multi-Threaded Pipeline Real-Time Inspection
        self.embed_queue: Optional[Any] = None
        self.db_queue: Optional[Any] = None
        self.active_http_workers: int = 0
        self.total_http_workers: int = int(getattr(settings, "KB_SIDECAR_HTTP_WORKERS", 4))
        self.producer_stage: str = "stopped"
        self.db_writer_stage: str = "stopped"
        self._workers_counter_lock = threading.Lock()

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
        """Get live status and progress counters of the continuous worker and queue pipeline."""
        with self._lock:
            now = time.time()
            uptime_seconds = int(now - self.session_start_time) if (self.is_running and self.session_start_time) else 0
            mins, secs = divmod(uptime_seconds, 60)
            uptime_fmt = f"{mins}m {secs}s" if mins else f"{secs}s"

            embed_q_depth = self.embed_queue.qsize() if (self.embed_queue and self.is_running) else 0
            db_q_depth = self.db_queue.qsize() if (self.db_queue and self.is_running) else 0

            return {
                "is_running": self.is_running and bool(self._thread and self._thread.is_alive()),
                "session_docs_processed": self.session_docs_processed,
                "session_chunks_embedded": self.session_chunks_embedded,
                "uptime_seconds": uptime_seconds,
                "uptime_formatted": uptime_fmt,
                "start_time": time.strftime("%H:%M:%S", time.localtime(self.session_start_time)) if self.session_start_time else None,
                "pipeline": {
                    "is_running": self.is_running and bool(self._thread and self._thread.is_alive()),
                    "producer_stage": self.producer_stage if self.is_running else "stopped",
                    "embed_queue_depth": embed_q_depth,
                    "embed_queue_max": 100,
                    "active_http_workers": self.active_http_workers if self.is_running else 0,
                    "total_http_workers": self.total_http_workers,
                    "db_queue_depth": db_q_depth,
                    "db_queue_max": 100,
                    "db_writer_stage": self.db_writer_stage if self.is_running else "stopped"
                }
            }

    def _pipeline_loop(self, poll_interval: float, external_stop_event=None) -> None:
        """Multithreaded pipeline: Producer (DB read) -> HTTP Workers (Embed) -> DB Writer (Persist)."""
        import queue
        from reposcroller.ai.telemetry import workload_telemetry
        
        stop_evt = external_stop_event if external_stop_event else self._stop_event
        
        logger.info(f"Starting Multi-Threaded Sidecar Pipeline (Producer, HTTP Pool, DB Writer) | Target: {settings.embed_url}")
        
        embed_queue = queue.Queue(maxsize=100)
        db_queue = queue.Queue(maxsize=100)
        self.embed_queue = embed_queue
        self.db_queue = db_queue
        self.producer_stage = "fetching_db"
        self.db_writer_stage = "idle_waiting"
        
        last_reported_hundred = 0
        is_idle_reported = False

        def db_writer_loop():
            while not stop_evt.is_set():
                try:
                    task = db_queue.get(timeout=poll_interval)
                except queue.Empty:
                    self.db_writer_stage = "idle_waiting"
                    continue
                if task is None:
                    break
                try:
                    self.db_writer_stage = "writing_sqlite"
                    docs_to_embed = task["docs_to_embed"]
                    doc_graphs = task["doc_graphs"]
                    completed_shas = task["completed_shas"]
                    total_batch_chunks = task["total_batch_chunks"]

                    # SQLite persistence (this calls vector_store and graph_store)
                    if docs_to_embed:
                        self.vector_store.index_batch_document_chunks(docs_to_embed)
                    if doc_graphs:
                        self.graph_store.save_graphs_batch(doc_graphs)
                    if completed_shas:
                        self.repo.mark_kb_queue_batch_status(completed_shas, "completed")
                        workload_telemetry.record_document_completed(count=len(completed_shas), chunks=total_batch_chunks)
                    
                    with self._lock:
                        self.session_docs_processed += len(completed_shas)
                        self.session_chunks_embedded += total_batch_chunks
                except Exception as e:
                    logger.error(f"Pipeline DB Writer error: {e}")
                finally:
                    self.db_writer_stage = "idle_waiting"
                    db_queue.task_done()

        def http_worker_loop():
            while not stop_evt.is_set():
                try:
                    batch = embed_queue.get(timeout=poll_interval)
                except queue.Empty:
                    continue
                if batch is None:
                    break
                try:
                    with self._workers_counter_lock:
                        self.active_http_workers += 1

                    docs_to_embed = batch["docs_to_embed"]
                    all_texts_to_embed = []
                    chunk_ptrs = []
                    
                    # Extract texts that need embeddings
                    for sha, chunks, _meta in docs_to_embed:
                        for c in chunks:
                            if not c.get("embedding"):
                                all_texts_to_embed.append(c["chunk_text"])
                                chunk_ptrs.append(c)

                    # HTTP requests are fully concurrent now, without blocking SQLite
                    if all_texts_to_embed:
                        embeddings = self.embedder.embed_batch(all_texts_to_embed)
                        for chunk_obj, emb in zip(chunk_ptrs, embeddings):
                            chunk_obj["embedding"] = emb
                            
                    db_queue.put(batch)
                except Exception as e:
                    logger.error(f"Pipeline HTTP worker error: {e}")
                    failed_shas = [sha for sha, _, _ in batch["docs_to_embed"]]
                    self.repo.mark_kb_queue_batch_status(failed_shas, "failed")
                finally:
                    with self._workers_counter_lock:
                        self.active_http_workers = max(0, self.active_http_workers - 1)
                    embed_queue.task_done()

        # Launch Thread Pool
        num_http_workers = self.total_http_workers
        http_threads = []
        for i in range(num_http_workers):
            t = threading.Thread(target=http_worker_loop, name=f"HTTP-Worker-{i}", daemon=True)
            t.start()
            http_threads.append(t)
            
        writer_thread = threading.Thread(target=db_writer_loop, name="DB-Writer", daemon=True)
        writer_thread.start()

        # Producer Loop (Main Thread)
        while not stop_evt.is_set():
            try:
                self.producer_stage = "fetching_db"
                pending_items = self.repo.fetch_pending_kb_queue(limit=settings.KB_SIDECAR_BATCH_SIZE)
                if not pending_items:
                    self.producer_stage = "idle_waiting"
                    if not is_idle_reported:
                        logger.info("⏳ [IDLE] All queued documents processed. Waiting for new files...")
                        is_idle_reported = True
                    time.sleep(poll_interval)
                    continue

                is_idle_reported = False
                batch_shas = [item["sha256_hash"] for item in pending_items]
                self.repo.mark_kb_queue_batch_status(batch_shas, "processing")

                self.producer_stage = "chunking"
                docs_to_embed = []
                doc_graphs = []
                completed_shas = []
                total_batch_chunks = 0

                for item in pending_items:
                    sha = item["sha256_hash"]
                    fname = item.get("canonical_filename", "")
                    doc_type = item.get("doc_type", "")
                    doc_date = item.get("doc_date", "")

                    full_text = self.repo.get_document_full_text(sha) or item.get("text_snippet", "")
                    if not full_text:
                        completed_shas.append(sha)
                        continue

                    chunks = self.chunker.chunk_document(full_text, sha, fname, doc_type, doc_date)
                    docs_to_embed.append((sha, chunks, item))

                    doc_graph = self.graph_extractor.extract_knowledge_graph(full_text, sha, fname, doc_type, doc_date)
                    doc_graphs.append(doc_graph)
                    completed_shas.append(sha)
                    total_batch_chunks += len(chunks)

                batch = {
                    "docs_to_embed": docs_to_embed,
                    "doc_graphs": doc_graphs,
                    "completed_shas": completed_shas,
                    "total_batch_chunks": total_batch_chunks
                }
                
                # Hand over to HTTP workers (Blocks if embed_queue is full at 100)
                embed_queue.put(batch)
                self.producer_stage = "queued"

                current_hundred = self.session_docs_processed // 100
                if current_hundred > last_reported_hundred:
                    last_reported_hundred = current_hundred
                    logger.info(f"⚡ Sidecar Milestone: {self.session_docs_processed} docs processed ({self.session_chunks_embedded} chunks/vectors) | Tier: {workload_telemetry.active_tier_label}")

            except Exception as e:
                logger.error(f"Error in Pipeline Producer loop: {e}")
                self.producer_stage = "error"
                time.sleep(poll_interval)

        # Graceful Teardown
        for _ in range(num_http_workers):
            embed_queue.put(None)
        db_queue.put(None)
        
        self.producer_stage = "stopped"
        self.db_writer_stage = "stopped"
        self.embed_queue = None
        self.db_queue = None
        logger.info("Sidecar Multithreaded pipeline exited gracefully.")

    def _run_loop(self, poll_interval: float = 2.0) -> None:
        """Internal worker loop running continuously until stop event is signaled."""
        self._pipeline_loop(poll_interval)

    def run_worker_loop(self, poll_interval: float = 3.0, stop_event=None) -> None:
        """CLI entrypoint for standalone background sidecar daemon."""
        self._pipeline_loop(poll_interval, stop_event)

