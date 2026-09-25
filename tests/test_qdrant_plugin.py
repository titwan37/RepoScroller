"""Tests for Qdrant Vector Store plugin and VectorStore integration."""

import pytest
from unittest.mock import MagicMock, patch
from reposcroller.ledger.qdrant_plugin import QdrantVectorStorePlugin
from reposcroller.ledger.vector_store import VectorStore
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.ai.embeddings import EmbeddingAdapter


def test_qdrant_plugin_offline_graceful_handling():
    """Verify that when Qdrant is unreachable or not installed, the plugin operates cleanly in offline mode."""
    with patch("reposcroller.ledger.qdrant_plugin.QdrantVectorStorePlugin._init_client") as mock_init:
        mock_init.return_value = None
        plugin = QdrantVectorStorePlugin(url="http://non-existent-host:6333")
        assert not plugin.is_available
        assert not plugin.ensure_collection(1024)
        assert plugin.upsert_chunks("fake_sha", []) == 0
        assert plugin.search_similar_chunks([0.1] * 1024) == []
        assert not plugin.delete_document_chunks("fake_sha")
        
        stats = plugin.get_stats()
        assert stats["available"] is False
        assert stats["status"] == "offline_or_disabled"


def test_qdrant_plugin_mock_operations():
    """Verify Qdrant plugin collection creation, point upsert, and search using mocked Qdrant client."""
    mock_client = MagicMock()
    mock_models = MagicMock()
    
    # Mock collections
    mock_col = MagicMock()
    mock_col.name = "test_col"
    mock_client.get_collections.return_value.collections = []

    # Mock search response
    mock_hit = MagicMock()
    mock_hit.score = 0.88
    mock_hit.payload = {
        "chunk_id": "sha123_0",
        "sha256_hash": "sha123",
        "chunk_text": "Sample text in Qdrant",
        "canonical_filename": "sample.pdf"
    }
    mock_client.search.return_value = [mock_hit]

    with patch.object(QdrantVectorStorePlugin, "_init_client"):
        plugin = QdrantVectorStorePlugin(collection_name="test_col")
        plugin._client = mock_client
        plugin._models = mock_models
        plugin._available = True

        assert plugin.is_available

        # 1. Collection creation
        created = plugin.ensure_collection(vector_size=1024)
        assert created is True
        mock_client.create_collection.assert_called_once()

        # 2. Upsert
        chunks = [
            {"chunk_index": 0, "chunk_text": "Sample text", "embedding": [0.1] * 1024}
        ]
        upserted = plugin.upsert_chunks("sha123", chunks, doc_metadata={"canonical_filename": "sample.pdf"})
        assert upserted == 1
        mock_client.upsert.assert_called_once()

        # 3. Search
        results = plugin.search_similar_chunks([0.1] * 1024, limit=5, min_similarity=0.5)
        assert len(results) == 1
        assert results[0]["similarity_score"] == 0.88
        assert results[0]["canonical_filename"] == "sample.pdf"

        # 4. Delete
        deleted = plugin.delete_document_chunks("sha123")
        assert deleted is True
        mock_client.delete.assert_called_once()


def test_vector_store_with_qdrant_integration(tmp_path):
    """Verify VectorStore seamlessly coordinates SQLite persistence and Qdrant plugin."""
    from reposcroller.ledger.db import init_db
    db_file = tmp_path / "test_vs_qdrant.db"
    init_db(db_file)
    repo = DocumentRepository(db_path=db_file)
    embedder = EmbeddingAdapter(provider="mock", dimension=64)

    # Ingest a sample doc in ledger
    repo.upsert_document(
        sha256_hash="doc_qdrant_test",
        simhash="111222333",
        canonical_filename="qdrant_test.pdf",
        doc_type="contract",
        lifecycle_status="final",
        completeness_score=1.0,
        maturity_score=0.95,
        page_count=1,
        text_snippet="Contract between Alpha and Beta",
        doc_date="2024-05-01"
    )

    mock_qdrant = MagicMock(spec=QdrantVectorStorePlugin)
    mock_qdrant.is_available = True
    mock_qdrant.search_similar_chunks.return_value = [
        {
            "chunk_id": "doc_qdrant_test_0",
            "sha256_hash": "doc_qdrant_test",
            "canonical_filename": "qdrant_test.pdf",
            "chunk_text": "Contract terms between Alpha and Beta",
            "similarity_score": 0.94
        }
    ]

    vs = VectorStore(repository=repo, embedding_adapter=embedder, qdrant_plugin=mock_qdrant)

    # 1. Indexing
    chunks = [
        {"chunk_index": 0, "chunk_text": "Contract terms between Alpha and Beta", "token_count": 6}
    ]
    count = vs.index_document_chunks("doc_qdrant_test", chunks, doc_metadata={"canonical_filename": "qdrant_test.pdf"})
    assert count == 1
    mock_qdrant.upsert_chunks.assert_called_once()

    # 2. Search (with Qdrant enabled in settings)
    with patch("reposcroller.ledger.vector_store.settings.VECTOR_STORE_TYPE", "qdrant"):
        hits = vs.search_similar_chunks("Alpha contract", limit=5)
        assert len(hits) == 1
        assert hits[0]["similarity_score"] == 0.94
        mock_qdrant.search_similar_chunks.assert_called_once()

    # 3. Search Fallback (with SQLite mode)
    with patch("reposcroller.ledger.vector_store.settings.VECTOR_STORE_TYPE", "sqlite"):
        hits_sql = vs.search_similar_chunks("Alpha contract", limit=5, min_similarity=0.0)
        assert len(hits_sql) >= 1
        assert hits_sql[0]["canonical_filename"] == "qdrant_test.pdf"

    # 4. Stats
    stats = vs.get_stats()
    assert "sqlite" in stats
    assert "qdrant" in stats
