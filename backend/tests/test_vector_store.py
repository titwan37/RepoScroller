"""Unit tests for VectorStore and SQLite chunk persistence."""

import pytest
from reposcroller.ledger.db import init_db
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.ledger.vector_store import VectorStore
from reposcroller.ai.embeddings import EmbeddingAdapter


def test_vector_store_indexing_and_search(tmp_path):
    db_file = tmp_path / "test_vector.db"
    init_db(db_file)
    repo = DocumentRepository(db_path=db_file)
    embedder = EmbeddingAdapter(provider="mock", dimension=64)

    vstore = VectorStore(repository=repo, embedding_adapter=embedder)

    sha = "test_sha_contract_999"
    repo.upsert_document(
        sha256_hash=sha,
        simhash="123456789",
        canonical_filename="Employment_Contract_Alice.pdf",
        doc_type="employment_contract",
        lifecycle_status="final",
        completeness_score=1.0,
        maturity_score=0.9,
        page_count=3,
        text_snippet="Alice agrees to work as Lead Developer.",
        doc_date="2024-06-01",
        full_text="Alice agrees to work as Lead Developer for SwissTech AG with standard notice."
    )

    chunks = [
        {
            "chunk_id": f"{sha}_0",
            "sha256_hash": sha,
            "chunk_index": 0,
            "chunk_text": "Alice agrees to work as Lead Developer for SwissTech AG.",
            "token_count": 10,
        },
        {
            "chunk_id": f"{sha}_1",
            "sha256_hash": sha,
            "chunk_index": 1,
            "chunk_text": "Termination notice period is three months at end of calendar month.",
            "token_count": 11,
        }
    ]

    indexed = vstore.index_document_chunks(sha, chunks)
    assert indexed == 2

    # Check persistence
    stored_chunks = repo.get_document_chunks(sha)
    assert len(stored_chunks) == 2
    assert stored_chunks[0]["embedding"] is not None
    assert len(stored_chunks[0]["embedding"]) == 64

    # Perform search
    results = vstore.search_similar_chunks(query="developer contract alice", limit=5)
    assert len(results) > 0
    assert results[0]["sha256_hash"] == sha
