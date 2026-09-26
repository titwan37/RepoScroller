import tempfile
import threading
from pathlib import Path
from reposcroller.ledger.db import init_db
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.ledger.graph_store import PropertyGraphStore
from reposcroller.ai.graph_schemas import EntityNode

def test_no_database_lock_when_queue_empty():
    """Verify that fetch_pending_kb_queue does not leave open write locks when empty."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test_ledger.db"
        init_db(db_file)
        repo = DocumentRepository(db_path=db_file)
        
        try:
            # 0. Insert document record first (satisfies foreign key)
            sha = "hash_12345"
            repo.upsert_document(
                sha256_hash=sha,
                simhash="0" * 16,
                canonical_filename="test.pdf",
                doc_type="pdf",
                lifecycle_status="draft",
                completeness_score=1.0,
                maturity_score=1.0,
                page_count=1,
                text_snippet="Sample document text for test"
            )

            # 1. Enqueue item
            repo.enqueue_kb_processing(sha)
            
            # 2. Fetch pending (queue becomes empty afterwards)
            items = repo.fetch_pending_kb_queue(limit=10)
            assert len(items) == 1
            assert items[0]["sha256_hash"] == sha
            
            # 3. Fetch pending when queue is empty (MUST NOT LEAVE UNCOMMITTED LOCK)
            empty_items = repo.fetch_pending_kb_queue(limit=10)
            assert len(empty_items) == 0
            
            # 4. Another operation on repository must succeed without 'database is locked'
            repo.mark_kb_queue_status(sha, "completed")
            stats = repo.get_kb_queue_stats()
            assert stats["completed"] == 1
        finally:
            repo.close()

def test_concurrent_threads_no_lock():
    """Verify concurrent threads calling fetch_pending_kb_queue and write operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test_ledger.db"
        init_db(db_file)
        repo = DocumentRepository(db_path=db_file)
        graph_store = PropertyGraphStore(repository=repo)
        
        try:
            errors = []
            def producer_worker():
                for _ in range(50):
                    try:
                        repo.fetch_pending_kb_queue(limit=5)
                    except Exception as e:
                        errors.append(e)

            def writer_worker():
                for i in range(50):
                    try:
                        node = EntityNode(node_id=f"node_{i}", node_type="person", name=f"Person {i}")
                        graph_store.upsert_node(node)
                    except Exception as e:
                        errors.append(e)

            t1 = threading.Thread(target=producer_worker)
            t2 = threading.Thread(target=writer_worker)
            
            t1.start()
            t2.start()
            t1.join()
            t2.join()
            
            assert len(errors) == 0, f"Thread errors encountered: {errors}"
        finally:
            repo.close()
