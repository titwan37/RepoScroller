"""Unit tests for streaming cryptographic hashing."""

import hashlib
from pathlib import Path
from reposcroller.integrity.hasher import compute_sha256, compute_bytes_sha256, compute_file_stats


def test_compute_sha256(tmp_path: Path):
    test_file = tmp_path / "sample.bin"
    content = b"RepoScroller ALCOA+ Cryptographic Verification Payload" * 1000
    test_file.write_bytes(content)

    expected_hash = hashlib.sha256(content).hexdigest()
    actual_hash = compute_sha256(test_file)

    assert actual_hash == expected_hash
    assert compute_bytes_sha256(content) == expected_hash


def test_compute_file_stats(tmp_path: Path):
    test_file = tmp_path / "stats_test.txt"
    test_file.write_text("Hello World", encoding="utf-8")

    size, mtime = compute_file_stats(test_file)
    assert size == len("Hello World")
    assert mtime > 0
