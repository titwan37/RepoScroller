"""Unit tests for the Knowledge Base processing queue and Sidecar Worker."""

import pytest
from reposcroller.ledger.db import init_db
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.ai.sidecar_worker import KnowledgeBaseSidecarWorker
from reposcroller.ai.embeddings import EmbeddingAdapter


def test_kb_queue_lifecycle(tmp_path):
    db_file = tmp_path / "test_kb_queue.db"
    init_db(db_file)
    repo = DocumentRepository(db_path=db_file)
    embedder = EmbeddingAdapter(provider="mock", dimension=64)

    worker = KnowledgeBaseSidecarWorker(repository=repo, embedding_adapter=embedder)

    sha = "test_doc_sha_12345"
    repo.upsert_document(
        sha256_hash=sha,
        simhash="987654321",
        canonical_filename="Tenancy_Agreement_2024.pdf",
        doc_type="lease_contract",
        lifecycle_status="final",
        completeness_score=1.0,
        maturity_score=0.95,
        page_count=4,
        text_snippet="Lease for apartment in Zurich.",
        doc_date="2024-04-01",
        full_text="Lease agreement between Landlord and Tenant for apartment located in Zurich, Switzerland. Monthly rent is CHF 2,500."
    )

    # 1. Enqueue document
    repo.enqueue_kb_processing(sha)

    stats = repo.get_kb_queue_stats()
    assert stats["pending"] == 1
    assert stats["completed"] == 0

    # 2. Process batch
    batch_res = worker.process_pending_batch(limit=10)
    assert batch_res["processed_count"] == 1
    assert batch_res["results"][0]["status"] == "completed"

    # 3. Verify status update & chunks indexed
    updated_stats = repo.get_kb_queue_stats()
    assert updated_stats["pending"] == 0
    assert updated_stats["completed"] == 1
    assert updated_stats["total_chunks_indexed"] >= 1
    assert updated_stats["total_documents_chunked"] == 1

    # 4. Verify chunks can be queried
    chunks = repo.get_document_chunks(sha)
    assert len(chunks) >= 1
    assert "Document: Tenancy_Agreement_2024.pdf" in chunks[0]["chunk_text"]
