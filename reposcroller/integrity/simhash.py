"""Locality-Sensitive Hashing (SimHash) for document text near-duplicate detection."""

import re
import hashlib
from typing import List, Union


def _token_hash64(token: str) -> int:
    """Produce a deterministic 64-bit integer hash for a given token string."""
    digest = hashlib.md5(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def tokenize_shingles(text: str, n: int = 3) -> List[str]:
    """Tokenize normalized text into words and character n-gram shingles."""
    cleaned = re.sub(r"\s+", " ", text.lower().strip())
    if not cleaned:
        return []

    words = re.findall(r"\b\w+\b", cleaned)
    shingles: List[str] = list(words)

    # Add character n-grams for typo & morphology tolerance
    compact = re.sub(r"[^\w]", "", cleaned)
    if len(compact) >= n:
        for i in range(len(compact) - n + 1):
            shingles.append(compact[i:i + n])

    return shingles


def compute_simhash(text: str, n_gram: int = 3) -> str:
    """Compute 64-bit SimHash hex string (16 characters) for document text.
    
    Empty text returns 16 zeros.
    """
    shingles = tokenize_shingles(text, n=n_gram)
    if not shingles:
        return "0000000000000000"

    v = [0] * 64
    for token in shingles:
        h = _token_hash64(token)
        for i in range(64):
            bit = (h >> i) & 1
            if bit == 1:
                v[i] += 1
            else:
                v[i] -= 1

    fingerprint = 0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= (1 << i)

    return f"{fingerprint:016x}"


def hamming_distance(hash1: Union[str, int], hash2: Union[str, int]) -> int:
    """Calculate the Hamming distance between two 64-bit SimHash hex strings or integers.
    
    Returns count of differing bits (0 to 64).
    """
    if isinstance(hash1, str):
        val1 = int(hash1, 16)
    else:
        val1 = hash1

    if isinstance(hash2, str):
        val2 = int(hash2, 16)
    else:
        val2 = hash2

    xor_val = val1 ^ val2
    return bin(xor_val).count("1")


def simhash_similarity(hash1: Union[str, int], hash2: Union[str, int]) -> float:
    """Calculate normalized similarity score [0.0, 1.0] from Hamming distance.
    
    1.0 means identical fingerprint (0 differing bits).
    0.0 means completely opposing bit vectors (64 differing bits).
    """
    dist = hamming_distance(hash1, hash2)
    return round(1.0 - (dist / 64.0), 4)
