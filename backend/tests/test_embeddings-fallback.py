"""Unit tests for the EmbeddingAdapter and cosine similarity."""

import sys
import pytest
from reposcroller.ai.embeddings import EmbeddingAdapter, cosine_similarity
from reposcroller.ai.telemetry import workload_telemetry

def test_embeddings_fallback():
    adapter = EmbeddingAdapter()
    print('Testing embed_text...')
    vec = adapter.embed_text('Sample contract agreement with Swisscom AG')
    print('Vector dim:', len(vec), 'Non-zero sum:', sum(abs(x) for x in vec[:10]))
    print('Active tier:', workload_telemetry.active_tier, 'Tier color:', workload_telemetry.active_tier_color, 'Label:', workload_telemetry.active_tier_label)
    assert workload_telemetry.active_tier == "cuda"

    print('\nTesting embed_batch...')
    vecs = adapter.embed_batch(['Doc 1 test', 'Doc 2 test'])
    print('Batch vectors count:', len(vecs), 'Dim:', len(vecs[0]))
    print('Active tier:', workload_telemetry.active_tier, 'Total chunks:', workload_telemetry.embed_total_chunks)
    assert workload_telemetry.active_tier == "cuda"



def test_embeddings_fallback2():
    # Test Tier 2 fallback by pointing base_url to unreachable port
    adapter_fallback = EmbeddingAdapter(base_url='http://192.0.2.1:11434', local_url='http://localhost:11434')
    print('Testing Tier 2 fallback to localhost...')
    vec = adapter_fallback.embed_text('Sample contract test')
    print('Tier 2 Vector dim:', len(vec))
    print('Active tier:', workload_telemetry.active_tier, 'Tier color:', workload_telemetry.active_tier_color)
    print('Fallback reason:', workload_telemetry.last_fallback_reason)

    # Test Tier 3 fallback by pointing both to unreachable ports
    adapter_offline = EmbeddingAdapter(base_url='http://192.0.2.1:11434', local_url='http://192.0.2.2:11434')
    print('\nTesting Tier 3 fallback to offline pseudo...')
    vec_off = adapter_offline.embed_text('Sample contract offline')
    print('Tier 3 Vector dim:', len(vec_off))
    print('Active tier:', workload_telemetry.active_tier, 'Tier color:', workload_telemetry.active_tier_color)
    print('Fallback reason:', workload_telemetry.last_fallback_reason)


    # Test Tier 2 fallback (PC2 closed port -> local Ollama port 11434)
    adapter_fallback = EmbeddingAdapter(base_url='http://127.0.0.1:19999', local_url='http://127.0.0.1:11434')
    vec = adapter_fallback.embed_text('Sample contract test')
    print('Tier 2 Vector dim:', len(vec))
    print('Active tier:', workload_telemetry.active_tier, 'Tier color:', workload_telemetry.active_tier_color)
    print('Fallback reason:', workload_telemetry.last_fallback_reason)

    # Test Tier 3 fallback (Both closed ports)
    adapter_offline = EmbeddingAdapter(base_url='http://127.0.0.1:19999', local_url='http://127.0.0.1:19998')
    vec_off = adapter_offline.embed_text('Sample contract offline')
    print('\nTier 3 Vector dim:', len(vec_off))
    print('Active tier:', workload_telemetry.active_tier, 'Tier color:', workload_telemetry.active_tier_color)
    print('Fallback reason:', workload_telemetry.last_fallback_reason)