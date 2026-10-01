"""Unit tests for the context-aware DocumentChunker."""

import pytest
from reposcroller.ai.chunker import DocumentChunker


def test_chunker_basic():
    chunker = DocumentChunker(chunk_size_tokens=20, chunk_overlap_tokens=5)
    text = "Word " * 50  # 50 words
    chunks = chunker.chunk_document(
        text=text,
        sha256_hash="test_sha_123",
        canonical_filename="test_doc.pdf",
        doc_type="contract",
        doc_date="2024-05-15"
    )

    assert len(chunks) > 1
    assert chunks[0]["sha256_hash"] == "test_sha_123"
    assert chunks[0]["chunk_index"] == 0
    assert "Document: test_doc.pdf" in chunks[0]["chunk_text"]
    assert "Category: CONTRACT" in chunks[0]["chunk_text"]
    assert "Date: 2024-05-15" in chunks[0]["chunk_text"]


def test_chunker_empty_text():
    chunker = DocumentChunker()
    chunks = chunker.chunk_document(text="", sha256_hash="empty_sha")
    assert chunks == []
