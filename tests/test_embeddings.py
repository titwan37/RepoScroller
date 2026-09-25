"""Unit tests for the EmbeddingAdapter and cosine similarity."""

import pytest
from reposcroller.ai.embeddings import EmbeddingAdapter, cosine_similarity


def test_cosine_similarity():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    assert cosine_similarity(v1, v2) == pytest.approx(1.0)

    v3 = [0.0, 1.0, 0.0]
    assert cosine_similarity(v1, v3) == pytest.approx(0.0)


def test_embedding_adapter_fallback():
    adapter = EmbeddingAdapter(provider="mock", dimension=128)
    vec1 = adapter.embed_text("Employment agreement for software engineer.")
    vec2 = adapter.embed_text("Employment contract for developer.")
    vec3 = adapter.embed_text("Completely unrelated culinary recipe for pasta.")

    assert len(vec1) == 128
    sim_related = cosine_similarity(vec1, vec2)
    sim_unrelated = cosine_similarity(vec1, vec3)

    assert sim_related > sim_unrelated


def test_embedding_adapter_batch():
    adapter = EmbeddingAdapter(provider="mock", dimension=64)
    texts = ["Doc 1 text", "Doc 2 text", "Doc 3 text"]
    batch_vecs = adapter.embed_batch(texts)

    assert len(batch_vecs) == 3
    assert all(len(v) == 64 for v in batch_vecs)
