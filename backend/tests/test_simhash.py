"""Unit tests for 64-bit Locality-Sensitive Hashing (SimHash)."""

from reposcroller.integrity.simhash import (
    compute_simhash,
    hamming_distance,
    simhash_similarity,
    tokenize_shingles,
)


def test_tokenize_shingles():
    tokens = tokenize_shingles("Contract agreement between parties", n=3)
    assert "contract" in tokens
    assert "agreement" in tokens
    assert len(tokens) > 5


def test_simhash_identical():
    text1 = "This is a legal decision by the Kantonsgericht on 2024-05-10."
    text2 = "This is a legal decision by the Kantonsgericht on 2024-05-10."

    h1 = compute_simhash(text1)
    h2 = compute_simhash(text2)

    assert h1 == h2
    assert hamming_distance(h1, h2) == 0
    assert simhash_similarity(h1, h2) == 1.0


def test_simhash_near_duplicate():
    text1 = "This is a legal decision by the Kantonsgericht regarding property tax in Zurich on 2024-05-10."
    text2 = "This is a legal decision by the Kantonsgericht regarding property taxes in Zurich on 2024-05-10."

    h1 = compute_simhash(text1)
    h2 = compute_simhash(text2)

    dist = hamming_distance(h1, h2)
    # Small differences should result in very low Hamming distance (<= 5)
    assert dist <= 5
    assert simhash_similarity(h1, h2) >= 0.90


def test_simhash_completely_distinct():
    text1 = "Swiss commercial law code article 12 section B regarding joint ventures."
    text2 = "Delicious recipe for Italian tiramisu with mascarpone and espresso."

    h1 = compute_simhash(text1)
    h2 = compute_simhash(text2)

    dist = hamming_distance(h1, h2)
    # Distinct documents will have high Hamming distance
    assert dist > 12
    assert simhash_similarity(h1, h2) < 0.85
